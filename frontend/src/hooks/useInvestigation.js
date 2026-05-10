import { useState, useCallback, useRef } from 'react'
import { useSSE } from './useSSE.js'
import { API_BASE } from '../config.js'

const INITIAL_STATE = { status: 'IDLE', stages: [], currentStage: null }
const TERMINAL = new Set(['COMPLETE', 'FAILED'])

/**
 * Manages the full investigation lifecycle.
 *
 * startInvestigation(seedText, depth)
 *   → POST /investigations → open SSE stream → update stages
 *   → on COMPLETE: GET /investigations/{id} → set report
 *
 * loadExisting(id)
 *   → directly GETs the report and sets status=COMPLETE
 *
 * reset()
 *   → returns to IDLE
 *
 * Returns { investigationState, report, startInvestigation, loadExisting, reset }
 *
 * investigationState shape:
 *   { status: 'IDLE'|'RUNNING'|'COMPLETE'|'FAILED', stages: [], currentStage: null }
 */
export function useInvestigation() {
  const [investigationState, setInvestigationState] = useState(INITIAL_STATE)
  const [report, setReport] = useState(null)
  const [sseUrl, setSseUrl] = useState(null)
  const investigationIdRef = useRef(null)

  const handleEvent = useCallback((event) => {
    const { stage, message, reason, investigation_id } = event

    setInvestigationState((prev) => {
      const newStages = [...prev.stages, { stage, message: message || reason || '' }]
      const status = TERMINAL.has(stage) ? stage : 'RUNNING'
      return { status, stages: newStages, currentStage: stage }
    })

    if (stage === 'COMPLETE') {
      const id = investigation_id || investigationIdRef.current
      if (id != null) {
        fetch(`${API_BASE}/investigations/${id}`)
          .then((r) => r.json())
          .then((data) => setReport(data))
          .catch(() => {
            setInvestigationState((prev) => ({
              ...prev,
              status: 'FAILED',
              stages: [...prev.stages, { stage: 'FAILED', message: 'Failed to load report' }],
              currentStage: 'FAILED',
            }))
          })
      }
    }
  }, [])

  useSSE(sseUrl, handleEvent)

  const _startWithUrl = useCallback(async (url, body) => {
    setInvestigationState({ status: 'RUNNING', stages: [], currentStage: null })
    setReport(null)
    setSseUrl(null)
    investigationIdRef.current = null

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const { investigation_id, cached } = await res.json()
      investigationIdRef.current = investigation_id

      if (cached) {
        // Skip SSE — load the cached report directly
        setInvestigationState({
          status: 'COMPLETE',
          stages: [{ stage: 'COMPLETE', message: 'Loaded from cache — no API calls used' }],
          currentStage: 'COMPLETE',
        })
        const reportRes = await fetch(`${API_BASE}/investigations/${investigation_id}`)
        if (!reportRes.ok) throw new Error(`HTTP ${reportRes.status}`)
        setReport(await reportRes.json())
      } else {
        setSseUrl(`${API_BASE}/investigations/${investigation_id}/stream`)
      }
    } catch (err) {
      setInvestigationState({
        status: 'FAILED',
        stages: [{ stage: 'FAILED', message: err.message }],
        currentStage: 'FAILED',
      })
    }
  }, [])

  const startInvestigation = useCallback((seedText, depth, narrativeLabel) =>
    _startWithUrl(`${API_BASE}/investigations`, { seed_text: seedText, depth, narrative_label: narrativeLabel || null }),
  [_startWithUrl])

  const startProfileInvestigation = useCallback((handlesText, depth, minClusterSize = 2, narrativeLabel) =>
    _startWithUrl(`${API_BASE}/investigations/profile`, {
      handles_text: handlesText,
      depth,
      min_cluster_size: minClusterSize,
      narrative_label: narrativeLabel || null,
    }),
  [_startWithUrl])

  const startReplyInvestigation = useCallback((tweetUrl, depth, narrativeLabel) =>
    _startWithUrl(`${API_BASE}/investigations/replies`, { tweet_url: tweetUrl, depth, narrative_label: narrativeLabel || null }),
  [_startWithUrl])

  const loadExisting = useCallback(async (id) => {
    setInvestigationState({ status: 'COMPLETE', stages: [], currentStage: 'COMPLETE' })
    setReport(null)
    setSseUrl(null)
    investigationIdRef.current = id
    try {
      const res = await fetch(`${API_BASE}/investigations/${id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setReport(await res.json())
    } catch {}
  }, [])

  const reset = useCallback(() => {
    setSseUrl(null)
    setInvestigationState(INITIAL_STATE)
    setReport(null)
    investigationIdRef.current = null
  }, [])

  return { investigationState, report, startInvestigation, startProfileInvestigation, startReplyInvestigation, loadExisting, reset }
}
