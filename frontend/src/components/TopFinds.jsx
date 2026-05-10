import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../config.js'

const VERDICTS = ['All', 'COORDINATED', 'UNCERTAIN', 'ORGANIC']
const PAGE_SIZE = 10

const PATTERN_LABEL = {
  COORDINATED_INAUTHENTIC: 'Coordinated Inauthentic',
  BURST_AMPLIFICATION:     'Burst Amplification',
  BOT_NETWORK:             'Bot Network',
  ORGANIC_AMPLIFICATION:   'Organic Amplification',
  INCONCLUSIVE:            'Inconclusive',
}

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function ConfidenceBar({ value }) {
  const pct = Math.round((value ?? 0) * 100)
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

export default function TopFinds({ onExplore }) {
  const [rows, setRows]           = useState([])
  const [loading, setLoading]     = useState(true)
  const [verdict, setVerdict]     = useState('All')
  const [offset, setOffset]       = useState(0)
  const [hasMore, setHasMore]     = useState(false)

  const fetchRows = useCallback(async (v, off, append) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: PAGE_SIZE, offset: off })
      if (v !== 'All') params.set('verdict', v)
      const res = await fetch(`${API_BASE}/investigations/top?${params}`)
      if (!res.ok) return
      const data = await res.json()
      setRows((prev) => append ? [...prev, ...data] : data)
      setHasMore(data.length === PAGE_SIZE)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setOffset(0)
    fetchRows(verdict, 0, false)
  }, [verdict, fetchRows])

  function loadMore() {
    const next = offset + PAGE_SIZE
    setOffset(next)
    fetchRows(verdict, next, true)
  }

  return (
    <div className="top-finds">
      <div className="tf-header">
        <div className="tf-title">Top Investigations</div>
        <div className="tf-subtitle">
          Ranked by confidence score — highest coordination signal first
        </div>
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
      </div>

      {rows.length === 0 && !loading && (
        <p className="tf-empty">No completed investigations yet. Run one to see results here.</p>
      )}

      {rows.length > 0 && (
        <div className="tf-table-wrap">
          <table className="tf-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Verdict</th>
                <th>Seed text</th>
                <th>Confidence</th>
                <th>Cell</th>
                <th>Pattern</th>
                <th>Origin</th>
                <th>Date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((inv, i) => (
                <tr key={inv.id} className="tf-row">
                  <td className="tf-rank">{offset + i + 1}</td>
                  <td>
                    <span className={`verdict-badge ${(inv.verdict ?? 'pending').toLowerCase()}`}>
                      {inv.verdict ?? '—'}
                    </span>
                  </td>
                  <td className="tf-seed">
                    {(inv.seed_text ?? '').slice(0, 72)}
                    {(inv.seed_text ?? '').length > 72 ? '…' : ''}
                  </td>
                  <td className="tf-conf-cell">
                    <ConfidenceBar value={inv.confidence} />
                  </td>
                  <td className="tf-num">{inv.cell_size ?? '—'}</td>
                  <td className="tf-pattern">
                    {PATTERN_LABEL[inv.pattern_type] ?? inv.pattern_type ?? '—'}
                  </td>
                  <td className="tf-origin">
                    {inv.origin_account ? `@${inv.origin_account}` : '—'}
                  </td>
                  <td className="tf-date">{formatDate(inv.ran_at)}</td>
                  <td>
                    <button
                      className="tf-explore-btn"
                      onClick={() => onExplore(inv.id)}
                    >
                      Explore
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loading && <p className="tf-loading">Loading…</p>}

      {hasMore && !loading && (
        <button className="tf-load-more" onClick={loadMore}>
          Load more
        </button>
      )}
    </div>
  )
}
