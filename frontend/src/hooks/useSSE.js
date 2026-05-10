import { useState, useEffect, useRef } from 'react'

/**
 * Connects to an SSE endpoint and calls onEvent for each message.
 *
 * - Reconnects automatically when url changes.
 * - Closes the source after COMPLETE or FAILED.
 * - Uses a ref for onEvent so the caller can provide an inline function
 *   without causing reconnects on every render.
 *
 * Returns { connected, error }
 */
export function useSSE(url, onEvent) {
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    if (!url) {
      setConnected(false)
      setError(null)
      return
    }

    setError(null)
    const es = new EventSource(url)

    es.onopen = () => setConnected(true)

    es.onmessage = (e) => {
      let data
      try { data = JSON.parse(e.data) } catch { return }
      onEventRef.current(data)
      if (data.stage === 'COMPLETE' || data.stage === 'FAILED') {
        es.close()
        setConnected(false)
      }
    }

    es.onerror = () => {
      setError('SSE connection error')
      setConnected(false)
      es.close()
    }

    return () => {
      es.close()
      setConnected(false)
    }
  }, [url])

  return { connected, error }
}
