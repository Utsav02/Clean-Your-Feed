const BUCKET_S   = 5 * 60
const BAR_W      = 4
const BAR_GAP    = 2
const BAR_STEP   = BAR_W + BAR_GAP
const PAD_LEFT   = 28
const PAD_BOTTOM = 32
const PAD_TOP    = 24   // extra room for PEAK label
const PAD_RIGHT  = 16
const CHART_H    = 120

function toHHMM(ts) {
  const d = new Date(ts * 1000)
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
}

export default function BurstTimeline({ tweetMatches }) {
  const timestamps = (tweetMatches ?? [])
    .map((t) => t.posted_at)
    .filter(Boolean)
    .sort((a, b) => a - b)

  if (timestamps.length < 2) return null

  const minTs      = timestamps[0]
  const maxTs      = timestamps[timestamps.length - 1]
  const numBuckets = Math.max(Math.ceil((maxTs - minTs) / BUCKET_S) + 1, 1)
  const buckets    = new Array(numBuckets).fill(0)

  timestamps.forEach((ts) => {
    const idx = Math.min(Math.floor((ts - minTs) / BUCKET_S), numBuckets - 1)
    buckets[idx]++
  })

  const maxCount   = Math.max(...buckets, 1)
  const svgW       = PAD_LEFT + numBuckets * BAR_STEP + PAD_RIGHT
  const svgH       = PAD_TOP + CHART_H + PAD_BOTTOM
  const labelEvery = Math.max(2, Math.ceil(numBuckets / 6))

  const burstIdx = buckets.indexOf(Math.max(...buckets))
  const burstX   = PAD_LEFT + burstIdx * BAR_STEP + BAR_W / 2

  // Build area polygon path (step chart with gradient fill)
  const areaPoints = []
  buckets.forEach((count, i) => {
    const x = PAD_LEFT + i * BAR_STEP
    const y = PAD_TOP + CHART_H - Math.max(1, (count / maxCount) * CHART_H)
    areaPoints.push(`${x},${y}`)
    areaPoints.push(`${x + BAR_W},${y}`)
  })
  const lastX = PAD_LEFT + numBuckets * BAR_STEP
  const baseY = PAD_TOP + CHART_H
  const areaPath = areaPoints.length
    ? `M${PAD_LEFT},${baseY} L${areaPoints.join(' L')} L${lastX},${baseY} Z`
    : ''

  // Burst zone: 3 buckets before and after peak
  const zoneStart = Math.max(0, burstIdx - 2)
  const zoneEnd   = Math.min(numBuckets - 1, burstIdx + 3)
  const zoneX1    = PAD_LEFT + zoneStart * BAR_STEP
  const zoneX2    = PAD_LEFT + zoneEnd * BAR_STEP

  const gradId = 'bt-area-grad'

  return (
    <div className="burst-timeline-wrap">
      <svg
        width="100%"
        viewBox={`0 0 ${svgW} ${svgH}`}
        style={{ display: 'block', overflow: 'visible' }}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor="#1A1A1A" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#1A1A1A" stopOpacity="0.04" />
          </linearGradient>
          <linearGradient id="bt-burst-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor="#C0392B" stopOpacity="0.12" />
            <stop offset="100%" stopColor="#C0392B" stopOpacity="0.03" />
          </linearGradient>
        </defs>

        {/* Burst zone shading */}
        <rect
          x={zoneX1}
          y={PAD_TOP}
          width={zoneX2 - zoneX1}
          height={CHART_H}
          fill="url(#bt-burst-grad)"
        />

        {/* Horizontal grid lines */}
        {[0.25, 0.5, 0.75, 1].map((frac) => (
          <line
            key={frac}
            x1={PAD_LEFT}
            y1={PAD_TOP + CHART_H - frac * CHART_H}
            x2={PAD_LEFT + numBuckets * BAR_STEP}
            y2={PAD_TOP + CHART_H - frac * CHART_H}
            stroke="#E5E5E0"
            strokeWidth="1"
            strokeDasharray="3 3"
          />
        ))}

        {/* Area fill */}
        {areaPath && <path d={areaPath} fill={`url(#${gradId})`} />}

        {/* Step line on top */}
        {areaPoints.length > 0 && (
          <polyline
            points={areaPoints.join(' ')}
            fill="none"
            stroke="#1A1A1A"
            strokeWidth="1.5"
          />
        )}

        {/* Burst peak line + label */}
        <line
          x1={burstX} y1={PAD_TOP}
          x2={burstX} y2={PAD_TOP + CHART_H}
          stroke="#C0392B"
          strokeWidth="1.5"
          strokeDasharray="4 2"
        />
        <text
          x={burstX}
          y={PAD_TOP - 6}
          fontSize="8"
          fill="#C0392B"
          fontWeight="700"
          textAnchor="middle"
          letterSpacing="0.08em"
        >
          PEAK
        </text>
        <circle cx={burstX} cy={PAD_TOP + CHART_H - (buckets[burstIdx] / maxCount) * CHART_H} r="3" fill="#C0392B" stroke="#fff" strokeWidth="1.5" />

        {/* X axis baseline */}
        <line
          x1={PAD_LEFT}
          y1={PAD_TOP + CHART_H}
          x2={PAD_LEFT + numBuckets * BAR_STEP}
          y2={PAD_TOP + CHART_H}
          stroke="#E5E5E0"
          strokeWidth="1"
        />

        {/* X axis labels */}
        {buckets.map((_, i) => {
          if (i % labelEvery !== 0) return null
          const lx = PAD_LEFT + i * BAR_STEP + BAR_W / 2
          const ly = PAD_TOP + CHART_H + 6
          return (
            <text
              key={i}
              x={lx}
              y={ly}
              fontSize="7"
              fill="#6B6B6B"
              textAnchor="end"
              transform={`rotate(-45, ${lx}, ${ly})`}
            >
              {toHHMM(minTs + i * BUCKET_S)}
            </text>
          )
        })}

        {/* Y axis labels */}
        <text x={PAD_LEFT - 4} y={PAD_TOP + CHART_H} fontSize="8" fill="#9B9B9B" textAnchor="end">0</text>
        <text x={PAD_LEFT - 4} y={PAD_TOP + 4}        fontSize="8" fill="#9B9B9B" textAnchor="end">{maxCount}</text>
      </svg>
    </div>
  )
}
