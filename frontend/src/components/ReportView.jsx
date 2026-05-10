import { useState, useEffect } from 'react'
import CytoscapeGraph from './CytoscapeGraph.jsx'
import BurstTimeline from './BurstTimeline.jsx'
import AccountList from './AccountList.jsx'
import MutationVariants from './MutationVariants.jsx'
import ProfileAnalysis from './ProfileAnalysis.jsx'
import EvidencePanel from './EvidencePanel.jsx'
import { API_BASE } from '../config.js'

const VERDICT_CLASS = {
  COORDINATED: 'coordinated',
  UNCERTAIN:   'uncertain',
  ORGANIC:     'organic',
}

const PATTERN_LABEL = {
  COORDINATED_INAUTHENTIC: 'Coordinated Inauthentic',
  BURST_AMPLIFICATION:     'Burst Amplification',
  BOT_NETWORK:             'Bot Network',
  ORGANIC_AMPLIFICATION:   'Organic Amplification',
  INCONCLUSIVE:            'Inconclusive',
}

const TABS = [
  { id: 'network',   label: 'Network Graph' },
  { id: 'timeline',  label: 'Tweet Volume' },
  { id: 'variants',  label: 'Copy Variants' },
  { id: 'evidence',  label: 'Evidence' },
  { id: 'profiles',  label: 'Profile Analysis' },
]

export default function ReportView({ report }) {
  const [selectedAccountId, setSelectedAccountId] = useState(null)
  const [labels,      setLabels]      = useState([])
  const [labelInput,  setLabelInput]  = useState('')
  const [labelOpen,   setLabelOpen]   = useState(false)
  const [labelSaving, setLabelSaving] = useState(false)
  const [activeTabs,  setActiveTabs]  = useState(['network'])

  function toggleTab(id) {
    setActiveTabs(prev =>
      prev.includes(id)
        ? prev.filter(t => t !== id)
        : [...prev, id]
    )
  }

  const { investigation, cell_members, tweet_matches } = report

  // Load existing labels on mount
  useEffect(() => {
    fetch(`${API_BASE}/investigations/${investigation.id}/labels`)
      .then((r) => r.json())
      .then(setLabels)
      .catch(() => {})
  }, [investigation.id])

  async function saveLabel(e) {
    e.preventDefault()
    if (!labelInput.trim() || labelSaving) return
    setLabelSaving(true)
    try {
      const res = await fetch(`${API_BASE}/investigations/${investigation.id}/label`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: labelInput.trim() }),
      })
      if (res.ok) {
        const updated = await fetch(`${API_BASE}/investigations/${investigation.id}/labels`)
        setLabels(await updated.json())
        setLabelInput('')
        setLabelOpen(false)
      }
    } finally {
      setLabelSaving(false)
    }
  }
  const verdictMod   = VERDICT_CLASS[investigation.verdict] ?? 'uncertain'
  const originMember = cell_members.find((m) => m.role === 'ORIGIN')

  const burstMinutes = investigation.burst_window_s != null
    ? Math.round(investigation.burst_window_s / 60)
    : null

  function muteListText() {
    return cell_members.map((m) => `@${m.handle}`).join('\n')
  }

  function handleCopy() {
    navigator.clipboard.writeText(muteListText()).catch(() => {})
  }

  function handleDownload() {
    const blob = new Blob([muteListText()], { type: 'text/plain' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `mute-list-${investigation.id}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="report-view">

      {/* ── Full-width verdict banner ───────────────────────────── */}
      <div className="verdict-banner">
        <div className="verdict-banner-left">
          <p className="verdict-banner-eyebrow">Investigation Verdict</p>
          <h1 className={`verdict-headline ${verdictMod}`}>
            {investigation.verdict ?? '—'}
          </h1>
        </div>
        <div className="verdict-banner-right">
          {originMember && (
            <p className="verdict-origin">
              Origin:{' '}
              <a
                href={`https://x.com/${originMember.handle}`}
                target="_blank"
                rel="noopener noreferrer"
                className="verdict-origin-link"
              >
                @{originMember.handle}
              </a>
            </p>
          )}
          <p className="verdict-pattern">
            Pattern: {PATTERN_LABEL[investigation.pattern_type] ?? investigation.pattern_type ?? '—'}
          </p>
          <div className="verdict-chips">
            <span className="verdict-chip">Conf: {investigation.confidence?.toFixed(2) ?? '—'}</span>
            <span className="verdict-chip">Cell: {investigation.cell_size ?? '—'}</span>
            {burstMinutes != null && (
              <span className="verdict-chip">Burst: {burstMinutes}m</span>
            )}
            <span className="verdict-chip">API: {investigation.api_calls_used ?? '—'}</span>
          </div>
          <div className="verdict-export">
            <button className="export-btn" onClick={handleCopy}>Copy mute list</button>
            <button className="export-btn" onClick={handleDownload}>Download .txt</button>
            <button className="export-btn" onClick={() => setLabelOpen((o) => !o)}>
              {labelOpen ? 'Cancel' : '+ Label'}
            </button>
          </div>

          {/* Existing labels */}
          {labels.length > 0 && (
            <div className="verdict-labels">
              {labels.map((l) => (
                <span key={l.id} className="verdict-label-chip">{l.label}</span>
              ))}
            </div>
          )}

          {/* Label input */}
          {labelOpen && (
            <form className="label-form" onSubmit={saveLabel}>
              <input
                className="label-input"
                value={labelInput}
                onChange={(e) => setLabelInput(e.target.value)}
                placeholder="e.g. Vancouver election 2026 — kareemformayor"
                autoFocus
              />
              <button className="export-btn" type="submit" disabled={labelSaving || !labelInput.trim()}>
                {labelSaving ? 'Saving…' : 'Save'}
              </button>
            </form>
          )}
        </div>
      </div>

      {/* ── Tab bar ────────────────────────────────────────────── */}
      <div className="report-tabs">
        <div className="report-tabs-row">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`report-tab${activeTabs.includes(tab.id) ? ' active' : ''}`}
              onClick={() => toggleTab(tab.id)}
            >
              {tab.label}
              {activeTabs.includes(tab.id) && <span className="report-tab-dot" />}
            </button>
          ))}
        </div>
        <p className="report-tabs-hint">Select one or more panels to display below</p>
      </div>

      {/* ── Selected panels rendered in tab order ──────────────── */}

      {activeTabs.includes('network') && (
        <div className="report-split">
          <div className="report-card report-card--graph">
            <div className="report-card-header">
              <h2 className="report-card-title">Network Graph</h2>
              <div className="graph-legend">
                <LegendItem color="#C0392B" label="ORIGIN" />
                <LegendItem color="#E67E22" label="AMPLIFIER" />
                <LegendItem color="#95A5A6" label="SUSPECTED" />
              </div>
            </div>
            <div className="report-card-body">
              <CytoscapeGraph
                members={cell_members}
                tweetMatches={tweet_matches}
                onSelectAccount={setSelectedAccountId}
                selectedAccountId={selectedAccountId}
              />
            </div>
          </div>

          <div className="report-card report-card--members">
            <div className="report-card-header">
              <h2 className="report-card-title">Cell Members</h2>
            </div>
            <div className="report-card-body report-card-body--scroll">
              <AccountList
                members={cell_members}
                onSelectAccount={setSelectedAccountId}
                selectedAccountId={selectedAccountId}
              />
            </div>
          </div>
        </div>
      )}

      {activeTabs.includes('timeline') && (
        <div className="report-card">
          <div className="report-card-header">
            <h2 className="report-card-title">Tweet Volume Over Time</h2>
          </div>
          <div className="report-card-body">
            <BurstTimeline tweetMatches={tweet_matches} />
          </div>
        </div>
      )}

      {activeTabs.includes('variants') && (
        <MutationVariants
          tweetMatches={tweet_matches}
          members={cell_members}
        />
      )}

      {activeTabs.includes('evidence') && (
        <EvidencePanel investigationId={investigation.id} />
      )}

      {activeTabs.includes('profiles') && (
        <ProfileAnalysis investigationId={investigation.id} />
      )}
    </div>
  )
}

function LegendItem({ color, label }) {
  return (
    <div className="legend-item">
      <div className="legend-dot" style={{ background: color }} />
      {label}
    </div>
  )
}
