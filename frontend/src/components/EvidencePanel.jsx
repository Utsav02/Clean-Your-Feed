import { useState, useEffect } from 'react'
import { API_BASE } from '../config.js'

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function formatRate(r) {
  if (r >= 50) return { label: `${r}/day`, flag: true }
  if (r >= 20) return { label: `${r}/day`, flag: false }
  return { label: `${r}/day`, flag: false }
}

function AccountAge({ createdAt }) {
  if (!createdAt) return <span className="ev-muted">Unknown</span>
  const months = Math.round((Date.now() / 1000 - createdAt) / 2592000)
  const years  = Math.floor(months / 12)
  const label  = years >= 1 ? `${years}y ${months % 12}m` : `${months}m`
  const fresh  = months < 6
  return (
    <span className={fresh ? 'ev-flag' : ''}>
      {formatDate(createdAt)}
      <span className="ev-age-sub"> ({label} old{fresh ? ' — recently created' : ''})</span>
    </span>
  )
}

function StatRow({ label, value, flagged, mono }) {
  return (
    <div className="ev-stat-row">
      <span className="ev-stat-label">{label}</span>
      <span className={`ev-stat-value${flagged ? ' ev-flag' : ''}${mono ? ' ev-mono' : ''}`}>
        {value}
      </span>
    </div>
  )
}

function AccountCard({ acct }) {
  const [expanded, setExpanded] = useState(false)
  const rate = formatRate(acct.tweet_rate)
  const highFF = acct.ff_ratio >= 3

  return (
    <div className={`ev-account-card${acct.weapon_account ? ' ev-account-card--weapon' : ''}`}>
      <div className="ev-account-head">
        <div className="ev-account-identity">
          <a
            href={`https://x.com/${acct.handle}`}
            target="_blank"
            rel="noopener noreferrer"
            className="ev-handle"
          >
            @{acct.handle}
          </a>
          <span className={`ev-role-badge ev-role-badge--${acct.role?.toLowerCase()}`}>
            {acct.role}
          </span>
          {acct.weapon_account && (
            <span className="ev-weapon-flag">WEAPON ACCOUNT</span>
          )}
        </div>
        <button
          className="ev-expand-btn"
          onClick={() => setExpanded(e => !e)}
        >
          {expanded ? 'Less' : 'More'}
        </button>
      </div>

      {/* Core stats always visible */}
      <div className="ev-stats">
        <StatRow label="Created"     value={<AccountAge createdAt={acct.created_at} />} />
        <StatRow label="Followers"   value={acct.followers ?? '—'} flagged={(acct.followers ?? 0) < 20} mono />
        <StatRow label="Following"   value={acct.following ?? '—'} mono />
        <StatRow label="F/F ratio"   value={`${acct.ff_ratio}:1`} flagged={highFF} mono />
        <StatRow label="Total tweets" value={acct.tweet_count?.toLocaleString() ?? '—'} mono />
        <StatRow label="Tweet rate"  value={rate.label} flagged={rate.flag} mono />
        <StatRow label="Bot score"   value={`${Math.round((acct.bot_score ?? 0) * 100)}%`} flagged={(acct.bot_score ?? 0) >= 0.6} mono />
        {acct.description && (
          <StatRow label="Bio" value={acct.description} />
        )}
      </div>

      {/* Repeated phrases */}
      {acct.repeated_phrases?.length > 0 && (
        <div className="ev-section">
          <div className="ev-section-label">Repeated phrases ({acct.repeated_phrases.length})</div>
          {acct.repeated_phrases.map((p, i) => (
            <div key={i} className="ev-repeated-row">
              <span className="ev-repeated-count">{p.count}×</span>
              <span className="ev-repeated-text">"{p.text.slice(0, 120)}{p.text.length > 120 ? '…' : ''}"</span>
            </div>
          ))}
        </div>
      )}

      {/* Recent tweets — only when expanded */}
      {expanded && acct.recent_tweets?.length > 0 && (
        <div className="ev-section">
          <div className="ev-section-label">Recent tweets</div>
          {acct.recent_tweets.map((t, i) => (
            <div key={i} className="ev-tweet-row">
              <span className="ev-tweet-date">{formatDate(t.posted_at)}</span>
              <span className="ev-tweet-text">{t.text.slice(0, 200)}{t.text.length > 200 ? '…' : ''}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function EvidencePanel({ investigationId }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    if (!investigationId) return
    setLoading(true)
    fetch(`${API_BASE}/investigations/${investigationId}/evidence`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [investigationId])

  if (loading) return (
    <div className="report-card">
      <div className="report-card-body"><p className="muted">Building evidence dossier…</p></div>
    </div>
  )
  if (error) return null
  if (!data || data.accounts.length === 0) return null

  const weaponAccounts   = data.accounts.filter(a => a.weapon_account)
  const highRateAccounts = data.accounts.filter(a => a.tweet_rate >= 20)
  const directAttacks    = data.direct_attacks ?? []

  return (
    <>
      {/* ── Evidence summary ─────────────────────────────────────── */}
      <div className="report-card">
        <div className="report-card-header">
          <h2 className="report-card-title">Evidence Dossier</h2>
          <span className="report-card-sub">
            Raw signals from stored data — no additional API calls
          </span>
        </div>
        <div className="report-card-body">

          {/* Callout chips */}
          <div className="ev-callout-row">
            {weaponAccounts.length > 0 && (
              <div className="ev-callout ev-callout--red">
                <span className="ev-callout-num">{weaponAccounts.length}</span>
                <span className="ev-callout-label">weapon account{weaponAccounts.length > 1 ? 's' : ''}<br/>(&lt;20 followers, &lt;50 tweets)</span>
              </div>
            )}
            {highRateAccounts.length > 0 && (
              <div className="ev-callout ev-callout--amber">
                <span className="ev-callout-num">{highRateAccounts.length}</span>
                <span className="ev-callout-label">high-velocity account{highRateAccounts.length > 1 ? 's' : ''}<br/>(20+ tweets/day)</span>
              </div>
            )}
            {directAttacks.length > 0 && (
              <div className="ev-callout ev-callout--red">
                <span className="ev-callout-num">{directAttacks.length}</span>
                <span className="ev-callout-label">direct attack{directAttacks.length > 1 ? 's' : ''}<br/>on seed author</span>
              </div>
            )}
            <div className="ev-callout ev-callout--neutral">
              <span className="ev-callout-num">{data.accounts.length}</span>
              <span className="ev-callout-label">accounts<br/>analysed</span>
            </div>
          </div>

          {/* Direct attacks block */}
          {directAttacks.length > 0 && (
            <div className="ev-attacks">
              <div className="ev-attacks-label">
                Direct attacks on @{data.seed_handle}
              </div>
              {directAttacks.map((a, i) => (
                <div key={i} className="ev-attack-row">
                  <a
                    href={`https://x.com/${a.author}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ev-attack-handle"
                  >
                    @{a.author}
                  </a>
                  <span className="ev-attack-date">{formatDate(a.posted_at)}</span>
                  <span className="ev-attack-text">"{a.text.slice(0, 200)}"</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Per-account dossiers ──────────────────────────────────── */}
      <div className="report-card">
        <div className="report-card-header">
          <h2 className="report-card-title">Account Dossiers</h2>
          <span className="report-card-sub">
            Infrastructure signals, tweet velocity, and repeated content per cell member
          </span>
        </div>
        <div className="report-card-body ev-dossier-grid">
          {data.accounts.map(acct => (
            <AccountCard key={acct.handle} acct={acct} />
          ))}
        </div>
      </div>
    </>
  )
}
