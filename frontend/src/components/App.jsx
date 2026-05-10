import { useState } from 'react'
import BudgetBar from './BudgetBar.jsx'
import InputPanel from './InputPanel.jsx'
import ProgressStream from './ProgressStream.jsx'
import ReportView from './ReportView.jsx'
import History from './History.jsx'
import { useInvestigation } from '../hooks/useInvestigation.js'

export default function App() {
  const { investigationState, report, startInvestigation, startProfileInvestigation, startReplyInvestigation, loadExisting, reset } =
    useInvestigation()
  const { status, stages } = investigationState

  const [activeTab,    setActiveTab]    = useState('investigate')
  const [activeLabel,  setActiveLabel]  = useState(null)

  const showProgress  = status === 'RUNNING' || (status === 'FAILED' && stages.length > 0)
  const reportReady   = status === 'COMPLETE' && report != null
  const reportLoading = status === 'COMPLETE' && report == null

  function handleExplore(id) {
    loadExisting(id)
    setActiveTab('investigate')
  }

  return (
    <div className="app-shell">
      <BudgetBar />

      <div className="app-nav">
        <div className="app-nav-inner">
          <div className="app-brand">
            <div className="app-brand-square" />
            <span className="app-brand-name">Clean Your Feed</span>
          </div>
          <div className="app-nav-links">
            <button
              className={`app-nav-link${activeTab === 'investigate' ? ' active' : ''}`}
              onClick={() => setActiveTab('investigate')}
            >
              Investigate
            </button>
            <button
              className={`app-nav-link${activeTab === 'history' ? ' active' : ''}`}
              onClick={() => setActiveTab('history')}
            >
              History
            </button>
          </div>
        </div>
      </div>

      <main className="app-container">
        {activeTab === 'investigate' && (
          <>
            <InputPanel
              onStart={startInvestigation}
              onStartProfile={startProfileInvestigation}
              onStartReplies={startReplyInvestigation}
              disabled={status === 'RUNNING'}
              activeLabel={activeLabel}
              onLabelChange={setActiveLabel}
            />

            {showProgress   && <ProgressStream stages={stages} />}
            {reportLoading  && <p className="report-loading">Loading report…</p>}
            {reportReady    && <ReportView report={report} onNewInvestigation={reset} />}
            {status === 'IDLE' && <History onSelect={loadExisting} compact />}
          </>
        )}

        {activeTab === 'history' && (
          <History onSelect={handleExplore} />
        )}
      </main>
    </div>
  )
}
