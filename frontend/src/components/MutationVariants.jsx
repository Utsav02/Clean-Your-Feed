/**
 * Three match tiers (from backend/core/matcher.py):
 *   EXACT    — identical (not shown here, counted in cell member match totals)
 *   FUZZY    — max(ratio, token_set_ratio) >= 0.80  — copy-paste variants
 *   SEMANTIC — token_set_ratio >= 0.65              — deliberate rewrites
 *
 * Shown in two side-by-side sections. SEMANTIC is more suspicious than FUZZY
 * because it implies human editorial effort to evade duplicate detection.
 */
export default function MutationVariants({ tweetMatches, members }) {
  const handleMap = Object.fromEntries(
    (members ?? []).map((m) => [m.account_id, m.handle])
  )

  const nonExact = (tweetMatches ?? [])
    .filter((t) => t.similarity < 1.0)
    .sort((a, b) => b.similarity - a.similarity)

  const fuzzyRaw    = nonExact.filter((t) => t.match_type !== 'SEMANTIC')
  const semanticRaw = nonExact.filter((t) => t.match_type === 'SEMANTIC')

  function dedupByText(list) {
    const map = new Map()
    for (const m of list) {
      if (!map.has(m.text)) map.set(m.text, { match: m, accounts: [] })
      if (m.account_id) map.get(m.text).accounts.push(m.account_id)
    }
    return Array.from(map.values())
  }

  const fuzzyVariants    = dedupByText(fuzzyRaw)
  const semanticVariants = dedupByText(semanticRaw)

  if (!tweetMatches?.length) return null
  if (!fuzzyVariants.length && !semanticVariants.length) return null

  return (
    <div className="mutation-sections">
      {fuzzyVariants.length > 0 && (
        <section className="mutation-section mutation-section--fuzzy">
          <div className="mutation-section-head">
            <h2 className="mutation-section-title">Copy-paste Variants</h2>
            <p className="mutation-section-sub">
              Accounts amplifying identical or near-identical text.
            </p>
          </div>
          <div className="mutation-items">
            {fuzzyVariants.map(({ match: t, accounts }, i) => {
              const firstHandle = handleMap[accounts[0]] ?? accounts[0]
              const othersCount = accounts.length - 1
              const isNearExact = t.similarity >= 0.90
              return (
                <div key={t.tweet_id ?? i} className="mutation-card">
                  <div className="mutation-card-meta">
                    <span className={`mutation-badge ${isNearExact ? 'near-exact' : 'variant'}`}>
                      {isNearExact ? 'NEAR-EXACT' : 'VARIANT'}
                    </span>
                    <span className="mutation-pct">{(t.similarity * 100).toFixed(1)}% match</span>
                  </div>
                  <p className="mutation-text">"{t.text}"</p>
                  <div className="mutation-attribution">
                    {firstHandle && <span className="mutation-handle">@{firstHandle}</span>}
                    {othersCount > 0 && (
                      <span className="mutation-others">+{othersCount} other{othersCount > 1 ? 's' : ''}</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {semanticVariants.length > 0 && (
        <section className="mutation-section mutation-section--semantic">
          <div className="mutation-section-head">
            <h2 className="mutation-section-title">Semantic Rewrites</h2>
            <p className="mutation-section-sub">
              Same vocabulary, restructured — human editorial effort to evade detection.
            </p>
          </div>
          <div className="mutation-items">
            {semanticVariants.map(({ match: t, accounts }, i) => {
              const firstHandle = handleMap[accounts[0]] ?? accounts[0]
              const othersCount = accounts.length - 1
              return (
                <div key={t.tweet_id ?? i} className="mutation-card">
                  <div className="mutation-card-meta">
                    <span className="mutation-badge semantic">SEMANTIC</span>
                    <span className="mutation-pct">{(t.similarity * 100).toFixed(1)}% match</span>
                  </div>
                  <p className="mutation-text">"{t.text}"</p>
                  <div className="mutation-attribution">
                    {firstHandle && <span className="mutation-handle">@{firstHandle}</span>}
                    {othersCount > 0 && (
                      <span className="mutation-others">+{othersCount} other{othersCount > 1 ? 's' : ''}</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
