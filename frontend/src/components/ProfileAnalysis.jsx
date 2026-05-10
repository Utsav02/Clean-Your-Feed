import { useState, useEffect } from 'react'
import { API_BASE } from '../config.js'

export default function ProfileAnalysis({ investigationId }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    if (!investigationId) return
    setLoading(true)
    setError(null)
    fetch(`${API_BASE}/investigations/${investigationId}/profile-analysis`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => { setData(d); setLoading(false) })
      .catch((e) => { setError(e.message); setLoading(false) })
  }, [investigationId])

  if (loading) return <div className="report-card"><div className="report-card-body"><p className="muted">Loading profile analysis…</p></div></div>
  if (error)   return <div className="report-card"><div className="report-card-body"><p className="muted">Profile analysis unavailable: {error}</p></div></div>
  if (!data)   return null

  const { accounts, shared_targets, theme_clusters, self_repetitions, timing, coordination_score, investigation_type } = data
  const isProfiles  = investigation_type === 'PROFILES'
  const hasShared   = shared_targets?.length > 0
  const hasClusters = theme_clusters?.length > 0

  // Find the account handle for a given account_id
  const handleOf = (account_id) =>
    accounts.find((a) => a.account_id === account_id)?.handle ?? account_id

  function fmtDelay(s) {
    if (s < 60)   return `${s}s`
    if (s < 3600) return `${Math.round(s/60)}m`
    return `${(s/3600).toFixed(1)}h`
  }

  return (
    <>
      {/* ── Cell coordination score ───────────────────────────── */}
      {coordination_score && (
        <div className="report-card">
          <div className="report-card-header">
            <h2 className="report-card-title">Cell Coordination Score</h2>
            <span className="report-card-sub">Aggregate signal — how coordinated is the cell as a whole, independent of individual bot scores</span>
          </div>
          <div className="report-card-body">
            <div className="coord-score-row">
              <div className="coord-score-number" style={{
                color: coordination_score.score >= 0.6 ? '#C0392B'
                     : coordination_score.score >= 0.3 ? '#E67E22' : '#27AE60'
              }}>
                {Math.round(coordination_score.score * 100)}
              </div>
              <div className="coord-score-label">/ 100</div>
              <div className="coord-score-evidence">
                {coordination_score.evidence.length === 0
                  ? <span className="muted">No strong coordination signals found.</span>
                  : coordination_score.evidence.map((e, i) => (
                    <div key={i} className="coord-evidence-item">▸ {e}</div>
                  ))
                }
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Timing analysis ───────────────────────────────────── */}
      {timing && (timing.creation_clusters?.length > 0 || timing.inter_reply_regularity?.length > 0 || (!isProfiles && timing.reply_speed?.length > 0)) && (
        <div className="report-card">
          <div className="report-card-header">
            <h2 className="report-card-title">Timing Signals</h2>
            <span className="report-card-sub">Coordination in when accounts acted — no new API calls</span>
          </div>
          <div className="report-card-body timing-body">

            {/* Speed cluster — not shown for PROFILES mode */}
            {!isProfiles && timing.speed_cluster?.length > 0 && (
              <div className="timing-section">
                <div className="timing-section-title">Reply speed cluster</div>
                {timing.speed_cluster.map((c, i) => (
                  <div key={i} className="timing-cluster-row">
                    <span className="timing-cluster-window">{fmtDelay(c.window_start)}–{fmtDelay(c.window_end)} after seed tweet</span>
                    <span className="timing-cluster-handles">{c.handles.map(h => `@${h}`).join(', ')}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Creation clusters */}
            {timing.creation_clusters?.length > 0 && (
              <div className="timing-section">
                <div className="timing-section-title">Account creation clusters</div>
                {timing.creation_clusters.map((c, i) => (
                  <div key={i} className="timing-cluster-row">
                    <span className="timing-cluster-window">{c.window_label} ({c.account_count} accounts within 30 days)</span>
                    <span className="timing-cluster-handles">{c.handles.map(h => `@${h}`).join(', ')}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Reply speed per account — not shown for PROFILES mode */}
            {!isProfiles && timing.reply_speed?.length > 0 && (
              <div className="timing-section">
                <div className="timing-section-title">Reply speed to seed tweet</div>
                <div className="timing-speed-list">
                  {timing.reply_speed.map((r) => (
                    <div key={r.account_id} className="timing-speed-row">
                      <span className="pa-target-handle">@{r.handle}</span>
                      <span className="timing-delay">{fmtDelay(r.delay_s)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Regularity */}
            {timing.inter_reply_regularity?.length > 0 && (
              <div className="timing-section">
                <div className="timing-section-title">Posting regularity (low = automated)</div>
                {timing.inter_reply_regularity.map((r) => (
                  <div key={r.account_id} className="timing-speed-row">
                    <span className="pa-target-handle">@{r.handle}</span>
                    <span className={`timing-cv ${r.cv < 0.3 ? 'timing-cv--suspicious' : ''}`}>
                      CV {r.cv} · avg gap {fmtDelay(r.mean_gap_s)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Per-account reply targets ─────────────────────────── */}
      <div className="report-card">
        <div className="report-card-header">
          <h2 className="report-card-title">Account Behaviour</h2>
          <span className="report-card-sub">Who cell members target in their tweet history — no new API calls</span>
        </div>
        <div className="report-card-body">
          {accounts.length === 0
            ? <p className="muted">No timeline data stored for cell members.</p>
            : (
              <div className="profile-analysis-grid">
                {accounts.map((acct) => (
                  <div key={acct.account_id} className="pa-account-card">
                    <div className="pa-account-header">
                      <a
                        href={`https://x.com/${acct.handle}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="pa-handle"
                      >
                        @{acct.handle}
                      </a>
                      <span className="pa-pill">
                        {Math.round(acct.reply_ratio * 100)}% replies
                      </span>
                    </div>
                    {acct.top_targets.length > 0
                      ? (
                        <div className="pa-targets">
                          <p className="pa-targets-label">Top targets</p>
                          {acct.top_targets.map((t) => (
                            <div key={t.handle} className="pa-target-row">
                              <span className="pa-target-handle">@{t.handle}</span>
                              <span className="pa-target-count">{t.count}×</span>
                            </div>
                          ))}
                        </div>
                      )
                      : <p className="muted pa-no-targets">No reply targets found in stored tweets.</p>
                    }
                    {self_repetitions?.[acct.account_id] > 0 && (
                      <p className="pa-self-rep">
                        Self-repeated {self_repetitions[acct.account_id]}× in own history
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )
          }
        </div>
      </div>

      {/* ── Shared targets across cell ────────────────────────── */}
      {hasShared && (
        <div className="report-card">
          <div className="report-card-header">
            <h2 className="report-card-title">Shared Targets</h2>
            <span className="report-card-sub">Accounts replied to by multiple cell members in their broader history</span>
          </div>
          <div className="report-card-body">
            <div className="pa-shared-list">
              {shared_targets.map((st) => (
                <div key={st.target} className="pa-shared-row">
                  <a
                    href={`https://x.com/${st.target}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="pa-shared-target"
                  >
                    @{st.target}
                  </a>
                  <span className="pa-shared-count">{st.account_count} accounts</span>
                  <span className="pa-shared-by">{st.by.map((h) => `@${h}`).join(', ')}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Thematic clusters in history ──────────────────────── */}
      {hasClusters && (
        <div className="report-card">
          <div className="report-card-header">
            <h2 className="report-card-title">Historical Themes</h2>
            <span className="report-card-sub">Recurring narratives in cell members' past replies</span>
          </div>
          <div className="report-card-body">
            {theme_clusters.map((c, i) => (
              <div key={i} className="pa-cluster">
                <div className="pa-cluster-header">
                  <span className={`variant-badge ${c.match_type === 'SEMANTIC' ? 'semantic' : c.similarity >= 0.90 ? 'exact' : 'fuzzy'}`}>
                    {c.match_type}
                  </span>
                  <span className="pa-cluster-sim">{Math.round(c.similarity * 100)}% match</span>
                  <span className="pa-cluster-count">{c.members.length} tweets · {new Set(c.members.map((m) => m.author_id)).size} accounts</span>
                </div>
                <p className="pa-cluster-text">"{c.representative_text}"</p>
                <div className="pa-cluster-members">
                  {[...new Set(c.members.map((m) => m.author_id))].slice(0, 5).map((aid) => (
                    <span key={aid} className="pa-cluster-handle">@{handleOf(aid)}</span>
                  ))}
                  {new Set(c.members.map((m) => m.author_id)).size > 5 && (
                    <span className="pa-cluster-more">+{new Set(c.members.map((m) => m.author_id)).size - 5} more</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
