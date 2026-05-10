import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../config.js'

const VERDICTS   = ['All', 'COORDINATED', 'UNCERTAIN', 'ORGANIC']
const TYPE_LABEL = { TWEET: 'Tweet', REPLIES: 'Replies', PROFILES: 'Profiles' }
const PAGE_SIZE  = 20

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function ConfBar({ value }) {
  const pct   = Math.round((value ?? 0) * 100)
  const color = pct >= 60 ? '#C0392B' : pct >= 30 ? '#E67E22' : '#95A5A6'
  return (
    <div className="tf-confidence">
      <div className="tf-confidence-track">
        <div className="tf-confidence-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="tf-confidence-label">{pct}%</span>
    </div>
  )
}

function InvRow({ inv, index, onSelect }) {
  return (
    <tr className="tf-row">
      <td className="tf-rank">{index}</td>
      <td className="tf-type">{TYPE_LABEL[inv.investigation_type] ?? inv.investigation_type ?? '—'}</td>
      <td>
        <span className={`verdict-badge ${(inv.verdict ?? 'pending').toLowerCase()}`}>
          {inv.verdict ?? '—'}
        </span>
      </td>
      <td className="tf-seed">
        {(inv.seed_text ?? '').slice(0, 60)}
        {(inv.seed_text ?? '').length > 60 ? '…' : ''}
      </td>
      <td className="tf-conf-cell"><ConfBar value={inv.confidence} /></td>
      <td className="tf-num">{inv.cell_size ?? '—'}</td>
      <td className="tf-type">{inv.depth_used ?? '—'}</td>
      <td className="tf-date">{formatDate(inv.ran_at)}</td>
      <td className="tf-date">{formatDate(inv.last_accessed_at)}</td>
      <td className="tf-num">{inv.access_count ?? 1}</td>
      <td>
        {inv.search_source === 'SCRAPER' && (
          <span className="tf-source-badge scraper" title="Data from free scraper">Free</span>
        )}
      </td>
      <td>
        {inv.narrative_labels?.length > 0 && (
          <span className="tf-label-chips">
            {inv.narrative_labels.map((nl) => (
              <span key={nl.label} className="tf-label-chip">
                {nl.label}{nl.seq != null ? ` #${nl.seq}` : ''}
              </span>
            ))}
          </span>
        )}
      </td>
      <td>
        <button className="tf-explore-btn" onClick={() => onSelect(inv.id)}>
          Open
        </button>
      </td>
    </tr>
  )
}

// ── Full table (History tab) ──────────────────────────────────────────────

function FullHistory({ onSelect }) {
  const [rows,         setRows]         = useState([])
  const [loading,      setLoading]      = useState(true)
  const [verdict,      setVerdict]      = useState('All')
  const [offset,       setOffset]       = useState(0)
  const [hasMore,      setHasMore]      = useState(false)
  const [narratives,   setNarratives]   = useState([])
  const [filterLabel,  setFilterLabel]  = useState(null)
  const [groupByLabel, setGroupByLabel] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/investigations/narratives`)
      .then((r) => r.json())
      .then(setNarratives)
      .catch(() => {})
  }, [])

  const fetch_ = useCallback(async (v, off, append) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: PAGE_SIZE, offset: off })
      if (v !== 'All') params.set('verdict', v)
      const res  = await fetch(`${API_BASE}/investigations/top?${params}`)
      if (!res.ok) return
      const data = await res.json()
      setRows((prev) => append ? [...prev, ...data] : data)
      setHasMore(data.length === PAGE_SIZE)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { setOffset(0); fetch_(verdict, 0, false) }, [verdict, fetch_])

  // Client-side filter by label (narrative_labels is now [{label, seq}])
  const visibleRows = filterLabel
    ? rows.filter((r) => r.narrative_labels?.some((nl) => nl.label === filterLabel))
    : rows

  // Group by label if requested
  function renderGrouped() {
    const groups = {}
    const unlabeled = []
    for (const inv of visibleRows) {
      if (!inv.narrative_labels?.length) { unlabeled.push(inv); continue }
      for (const nl of inv.narrative_labels) {
        if (!groups[nl.label]) groups[nl.label] = []
        groups[nl.label].push(inv)
      }
    }
    const sections = []
    let globalIdx = 1
    for (const [lbl, invs] of Object.entries(groups)) {
      sections.push(
        <tbody key={lbl}>
          <tr className="tf-group-header">
            <td colSpan={13}><span className="tf-group-label">{lbl}</span></td>
          </tr>
          {invs.map((inv) => <InvRow key={inv.id} inv={inv} index={globalIdx++} onSelect={onSelect} />)}
        </tbody>
      )
    }
    if (unlabeled.length) {
      sections.push(
        <tbody key="__unlabeled">
          <tr className="tf-group-header">
            <td colSpan={13}><span className="tf-group-label tf-group-label--muted">Unlabeled</span></td>
          </tr>
          {unlabeled.map((inv) => <InvRow key={inv.id} inv={inv} index={globalIdx++} onSelect={onSelect} />)}
        </tbody>
      )
    }
    return sections
  }

  return (
    <div className="top-finds">
      <div className="tf-header">
        <div className="tf-title">Investigation History</div>
        <div className="tf-subtitle">All completed investigations, ranked by confidence</div>
      </div>

      <div className="tf-filters">
        {VERDICTS.map((v) => (
          <button
            key={v}
            className={`tf-filter-pill${verdict === v ? ' selected' : ''}`}
            onClick={() => setVerdict(v)}
          >
            {v}
          </button>
        ))}

        {narratives.length > 0 && (
          <>
            <span className="tf-filter-sep">|</span>
            <button
              className={`tf-filter-pill${filterLabel === null ? '' : ' selected'}`}
              onClick={() => setFilterLabel(null)}
            >
              All labels
            </button>
            {narratives.map((n) => (
              <button
                key={n.label}
                className={`tf-filter-pill${filterLabel === n.label ? ' selected' : ''}`}
                onClick={() => setFilterLabel(filterLabel === n.label ? null : n.label)}
              >
                {n.label}
              </button>
            ))}
            <button
              className={`tf-filter-pill${groupByLabel ? ' selected' : ''}`}
              onClick={() => setGroupByLabel((g) => !g)}
              title="Group rows by narrative label"
            >
              Group
            </button>
          </>
        )}
      </div>

      {visibleRows.length === 0 && !loading && (
        <p className="tf-empty">No completed investigations yet.</p>
      )}

      {visibleRows.length > 0 && (
        <div className="tf-table-wrap">
          <table className="tf-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Type</th>
                <th>Verdict</th>
                <th>Seed</th>
                <th>Confidence</th>
                <th>Cell</th>
                <th>Depth</th>
                <th>Ran</th>
                <th>Last opened</th>
                <th>Opens</th>
                <th>Source</th>
                <th>Labels</th>
                <th></th>
              </tr>
            </thead>
            {groupByLabel
              ? renderGrouped()
              : (
                <tbody>
                  {visibleRows.map((inv, i) => (
                    <InvRow key={inv.id} inv={inv} index={offset + i + 1} onSelect={onSelect} />
                  ))}
                </tbody>
              )
            }
          </table>
        </div>
      )}

      {loading && <p className="tf-loading">Loading…</p>}
      {hasMore && !loading && (
        <button className="tf-load-more" onClick={() => {
          const next = offset + PAGE_SIZE
          setOffset(next)
          fetch_(verdict, next, true)
        }}>
          Load more
        </button>
      )}
    </div>
  )
}

// ── Compact inline list (shown on Investigate tab when idle) ─────────────

function CompactHistory({ onSelect }) {
  const [expanded, setExpanded]   = useState(false)
  const [rows,     setRows]       = useState([])
  const [loading,  setLoading]    = useState(true)

  useEffect(() => {
    fetch(`${API_BASE}/investigations`)
      .then((r) => r.json())
      .then(setRows)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (!loading && rows.length === 0) return null

  return (
    <div className="past-investigations">
      <button
        className="past-investigations-toggle"
        onClick={() => setExpanded((e) => !e)}
      >
        Past investigations {expanded ? '▴' : '▾'}
      </button>

      {expanded && (
        <div>
          {loading && <p className="past-loading">Loading…</p>}
          {rows.map((inv) => (
            <div key={inv.id} className="past-row" onClick={() => onSelect(inv.id)}>
              <span className={`verdict-badge ${(inv.verdict ?? inv.status ?? 'pending').toLowerCase()}`}>
                {inv.verdict ?? inv.status}
              </span>
              <span className="past-type">{TYPE_LABEL[inv.investigation_type] ?? ''}</span>
              <span className="past-seed-text">
                {(inv.seed_text ?? '').slice(0, 60)}
                {(inv.seed_text ?? '').length > 60 ? '…' : ''}
              </span>
              <span className="past-date">{formatDate(inv.ran_at)}</span>
              <span className="past-cell-size">
                {inv.cell_size != null ? `${inv.cell_size} accts` : '—'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Exported component ───────────────────────────────────────────────────

export default function History({ onSelect, compact }) {
  return compact
    ? <CompactHistory onSelect={onSelect} />
    : <FullHistory    onSelect={onSelect} />
}
