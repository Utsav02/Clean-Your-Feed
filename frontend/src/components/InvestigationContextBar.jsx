import { useState, useEffect } from 'react'
import { API_BASE } from '../config.js'

/**
 * Persistent shell above the tabs.
 * Lets the user pick (or create) a narrative label that is automatically
 * attached to every investigation started in this session.
 */
export default function InvestigationContextBar({ activeLabel, onChange }) {
  const [narratives, setNarratives] = useState([])
  const [adding,     setAdding]     = useState(false)
  const [draft,      setDraft]      = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/investigations/narratives`)
      .then((r) => r.json())
      .then(setNarratives)
      .catch(() => {})
  }, [])

  function handleSelect(label) {
    onChange(activeLabel === label ? null : label)
  }

  function handleAdd() {
    const trimmed = draft.trim()
    if (!trimmed) { setAdding(false); setDraft(''); return }
    // Optimistically add to list and select it
    if (!narratives.find((n) => n.label === trimmed)) {
      setNarratives((prev) => [...prev, { id: null, label: trimmed }])
    }
    onChange(trimmed)
    setAdding(false)
    setDraft('')
  }

  return (
    <div className="ctx-bar">
      <span className="ctx-bar-label">Narrative context</span>

      <div className="ctx-bar-pills">
        {narratives.map((n) => (
          <button
            key={n.label}
            className={`ctx-bar-pill${activeLabel === n.label ? ' active' : ''}`}
            onClick={() => handleSelect(n.label)}
          >
            {n.label}
          </button>
        ))}

        {adding ? (
          <span className="ctx-bar-add-form">
            <input
              className="ctx-bar-input"
              autoFocus
              placeholder="New label…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAdd()
                if (e.key === 'Escape') { setAdding(false); setDraft('') }
              }}
            />
            <button className="ctx-bar-confirm" onClick={handleAdd}>Add</button>
            <button className="ctx-bar-cancel" onClick={() => { setAdding(false); setDraft('') }}>✕</button>
          </span>
        ) : (
          <button className="ctx-bar-new" onClick={() => setAdding(true)}>+ New</button>
        )}
      </div>

      {activeLabel && (
        <span className="ctx-bar-active-note">
          All new investigations will be tagged <strong>{activeLabel}</strong>
          <button className="ctx-bar-clear" onClick={() => onChange(null)}>Clear</button>
        </span>
      )}
    </div>
  )
}
