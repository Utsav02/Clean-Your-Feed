import { useEffect, useRef } from 'react'

const ROLE_COLOR = {
  ORIGIN:    '#C0392B',
  AMPLIFIER: '#E67E22',
  SUSPECTED: '#95A5A6',
}

export default function AccountList({ members, onSelectAccount, selectedAccountId }) {
  const rowRefs = useRef({})

  useEffect(() => {
    const el = rowRefs.current[selectedAccountId]
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [selectedAccountId])

  if (!members?.length) return null

  return (
    <div className="account-list-wrap">
      <div className="account-table-head">
        <span>Handle</span>
        <span>Role</span>
        <span>Bot Score</span>
        <span className="center">Seen In</span>
        <span className="center">Matches</span>
      </div>
      <div className="account-table-body">
        {members.map((m, idx) => {
          const isSelected  = m.account_id === selectedAccountId
          const isRepeat    = (m.investigation_count ?? 1) >= 3
          const roleColor   = ROLE_COLOR[m.role] ?? '#95A5A6'
          const botScorePct = ((m.bot_score ?? 0) * 100).toFixed(0)

          return (
            <div
              key={m.account_id}
              className={`account-row${isSelected ? ' selected' : ''}${idx % 2 === 0 ? ' even' : ' odd'}`}
              style={{ borderLeftColor: isSelected ? roleColor : 'transparent' }}
              onClick={() => onSelectAccount(m.account_id)}
              ref={(el) => { rowRefs.current[m.account_id] = el }}
            >
              <span className="account-handle">@{m.handle}</span>
              <span>
                <span className="role-badge" style={{ background: roleColor }}>
                  {m.role}
                </span>
              </span>
              <div className="bot-score-cell">
                <span className="bot-score-text">
                  {m.bot_score != null ? m.bot_score.toFixed(2) : '—'}
                </span>
                <div className="bot-score-bar">
                  <div className="bot-score-fill" style={{ width: `${botScorePct}%` }} />
                </div>
              </div>
              <span className={`center${isRepeat ? ' repeat-offender' : ''}`}>
                {m.investigation_count ?? 1}
              </span>
              <span className="center">{m.match_count ?? 0}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
