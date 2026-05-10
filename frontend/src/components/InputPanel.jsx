import { useState, useEffect } from 'react'
import { API_BASE } from '../config.js'

const DEPTHS = [
  { id: 'QUICK',    label: 'QUICK',    sub: '5 expansions · 5 API calls' },
  { id: 'STANDARD', label: 'STANDARD', sub: '10 expansions · 30 API calls' },
  { id: 'DEEP',     label: 'DEEP',     sub: '20 expansions · 100 API calls' },
]

const MODES = [
  {
    id:          'tweet',
    label:       'Tweet / URL',
    placeholder: 'Paste a tweet URL or tweet text…',
    btnLabel:    'Investigate',
  },
  {
    id:          'replies',
    label:       'Replies',
    placeholder: 'Paste a tweet URL to investigate its reply section…',
    btnLabel:    'Investigate Replies',
  },
  {
    id:          'profiles',
    label:       'Profiles',
    placeholder: 'Paste @handles to investigate — one per line or comma-separated…',
    btnLabel:    'Investigate Profiles',
  },
]

export default function InputPanel({ onStart, onStartProfile, onStartReplies, disabled, activeLabel, onLabelChange }) {
  const [mode,       setMode]       = useState('tweet')
  const [seedText,   setSeedText]   = useState('')
  const [depth,      setDepth]      = useState('STANDARD')
  const [narratives, setNarratives] = useState([])
  const [adding,     setAdding]     = useState(false)
  const [draft,      setDraft]      = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/investigations/narratives`)
      .then((r) => r.json())
      .then(setNarratives)
      .catch(() => {})
  }, [])

  const currentMode = MODES.find((m) => m.id === mode)

  function handleSubmit(e) {
    e.preventDefault()
    if (!seedText.trim() || disabled) return
    if (mode === 'profiles') {
      onStartProfile(seedText.trim(), depth, 2, activeLabel)
    } else if (mode === 'replies') {
      onStartReplies(seedText.trim(), depth, activeLabel)
    } else {
      onStart(seedText.trim(), depth, activeLabel)
    }
  }

  function selectLabel(label) {
    onLabelChange(activeLabel === label ? null : label)
  }

  function confirmAdd() {
    const trimmed = draft.trim()
    if (!trimmed) { setAdding(false); setDraft(''); return }
    if (!narratives.find((n) => n.label === trimmed)) {
      setNarratives((prev) => [...prev, { id: null, label: trimmed }])
    }
    onLabelChange(trimmed)
    setAdding(false)
    setDraft('')
  }

  return (
    <div className="input-panel">
      <div className="input-mode-toggle">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`input-mode-btn${mode === m.id ? ' selected' : ''}`}
            onClick={() => { setMode(m.id); setSeedText('') }}
            disabled={disabled}
          >
            {m.label}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit}>
        <textarea
          className="seed-textarea"
          value={seedText}
          onChange={(e) => setSeedText(e.target.value)}
          placeholder={currentMode.placeholder}
          disabled={disabled}
          rows={4}
        />

        {/* ── Narrative context row ── */}
        <div className="narrative-row">
          <span className="narrative-row-label">NARRATIVE</span>
          <div className="narrative-row-pills">
            {narratives.map((n) => (
              <button
                key={n.label}
                type="button"
                className={`narrative-pill${activeLabel === n.label ? ' selected' : ''}`}
                onClick={() => selectLabel(n.label)}
                disabled={disabled}
              >
                {n.label}
              </button>
            ))}

            {adding ? (
              <>
                <input
                  className="narrative-draft-input"
                  autoFocus
                  placeholder="Label name…"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') { e.preventDefault(); confirmAdd() }
                    if (e.key === 'Escape') { setAdding(false); setDraft('') }
                  }}
                />
                <button type="button" className="narrative-pill" onClick={confirmAdd}>Add</button>
                <button type="button" className="narrative-pill" onClick={() => { setAdding(false); setDraft('') }}>✕</button>
              </>
            ) : (
              <button
                type="button"
                className="narrative-pill narrative-pill--new"
                onClick={() => setAdding(true)}
                disabled={disabled}
              >
                + New
              </button>
            )}
          </div>

          {activeLabel && (
            <button
              type="button"
              className="narrative-clear"
              onClick={() => onLabelChange(null)}
            >
              Clear
            </button>
          )}
        </div>

        <div className="depth-selector">
          {DEPTHS.map((d) => (
            <button
              key={d.id}
              type="button"
              className={`depth-card${depth === d.id ? ' selected' : ''}`}
              onClick={() => setDepth(d.id)}
              disabled={disabled}
            >
              {depth === d.id && <div className="depth-card-accent" />}
              <span className="depth-card-label">{d.label}</span>
              <span className="depth-card-sub">{d.sub}</span>
            </button>
          ))}
        </div>

        <button
          type="submit"
          className="investigate-btn"
          disabled={disabled || !seedText.trim()}
        >
          {disabled ? 'Investigating…' : currentMode.btnLabel}
        </button>
      </form>
    </div>
  )
}
