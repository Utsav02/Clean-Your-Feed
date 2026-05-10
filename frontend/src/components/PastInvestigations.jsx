import { useState, useEffect } from 'react'
import { API_BASE } from '../config.js'

function verdictBadgeClass(verdict) {
  if (!verdict) return 'verdict-badge pending'
  return `verdict-badge ${verdict.toLowerCase()}`
}

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

export default function PastInvestigations({ onSelect }) {
  const [expanded, setExpanded]           = useState(false)
  const [investigations, setInvestigations] = useState([])
  const [loading, setLoading]             = useState(true)

  useEffect(() => {
    fetchInvestigations()
  }, [])

  async function fetchInvestigations() {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/investigations`)
      if (!res.ok) return
      setInvestigations(await res.json())
    } finally {
      setLoading(false)
    }
  }

  if (!loading && investigations.length === 0) return null

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

          {investigations.map((inv) => (
            <div
              key={inv.id}
              className="past-row"
              onClick={() => onSelect(inv.id)}
            >
              <span className={verdictBadgeClass(inv.verdict)}>
                {inv.verdict ?? inv.status}
              </span>
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
