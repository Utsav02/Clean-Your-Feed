const PIPELINE = ['SEARCHING', 'PROFILING', 'EXPANDING', 'ANALYZING']
const TERMINAL = new Set(['COMPLETE', 'FAILED'])

export default function ProgressStream({ stages }) {
  if (!stages.length) return null

  const lastStage = stages[stages.length - 1]
  const lastMessage = lastStage?.message || ''
  const currentPipelineStage = lastStage?.stage

  const isComplete = currentPipelineStage === 'COMPLETE'
  const isFailed   = currentPipelineStage === 'FAILED'
  const isRunning  = !isComplete && !isFailed

  // Find how far we are through the pipeline
  const currentIdx = PIPELINE.indexOf(currentPipelineStage)

  // Progress bar width: 0% before first stage, 100% when complete
  const progressPct = isComplete
    ? 100
    : currentIdx >= 0
    ? (currentIdx / (PIPELINE.length - 1)) * 100
    : 0

  return (
    <div className="progress-stream">
      <p className="progress-stream-title">Pipeline Status</p>

      {/* Horizontal pipeline */}
      <div className="pipeline-track">
        <div className="pipeline-rail" />
        <div className="pipeline-rail-fill" style={{ width: `${progressPct}%` }} />

        {PIPELINE.map((stage, idx) => {
          const isPassed = isComplete || idx < currentIdx
          const isActive = idx === currentIdx && !isComplete

          return (
            <div key={stage} className="pipeline-node-wrap">
              <div className={`pipeline-dot${isPassed ? ' passed' : isActive ? ' active' : ''}`} />
              <span className={`pipeline-label${isPassed || isActive ? ' lit' : ''}`}>{stage}</span>
            </div>
          )
        })}
      </div>

      {/* Cinematic message box */}
      <div className={`pipeline-message-box${isFailed ? ' failed' : ''}`}>
        {isRunning && <div className="pipeline-cursor" />}
        <span className="pipeline-message-text">
          {isComplete
            ? 'Investigation complete. Report generated.'
            : lastMessage || 'Waiting…'}
        </span>
      </div>
    </div>
  )
}
