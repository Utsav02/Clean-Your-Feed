# Clean Your Feed — Claude Context

## What this is
A journalistic tool that investigates coordinated inauthentic behaviour on X (Twitter).
User pastes a tweet URL or text → pipeline searches X API → scores accounts → detects coordination cells → renders report.

## How to run
```bash
export PATH="$HOME/.local/bin:$PATH"   # poetry not on PATH by default
cd /Users/utsavsingh/Desktop/Post-Uni/Clean-Your-Feed
poetry run uvicorn backend.main:app --reload   # backend :8000
cd frontend && npm run dev                      # frontend :5173
```
Requires `X_BEARER_TOKEN` in `.env`.
X API is **pay-as-you-go** (since Feb 2026) — credits are deducted per call. Rates: post read = $0.005, user profile lookup = $0.01, post creation = $0.01. Same resource within a 24h UTC window is deduplicated (charged once). Cap: 2M post reads/month before Enterprise is required. Budget tracking in `call_manager.py` is financially load-bearing, not a soft guard.

## Stack
- **Backend**: FastAPI + aiosqlite + httpx + rapidfuzz + python-dotenv (Poetry, Python 3.13)
- **Frontend**: React + Vite, Cytoscape.js loaded from CDN (not npm), SVG charts hand-rolled
- **DB**: SQLite at `data/feed_cleaner.db`

---

## Backend architecture

### Pipeline stages (investigator.py)
`PENDING → SEARCHING → PROFILING → EXPANDING → ANALYZING → COMPLETE`
Side states: `FAILED`, `PARTIAL`

**SEARCHING**
1. `extract_tweet_id(seed_text)` — regex for x.com/twitter.com URLs → calls `get_tweet_by_id` to resolve tweet text
2. `clean_seed_text()` — strips URLs, @mentions, #hashtags, collapses whitespace
3. Build `search_phrase` = first 6 words of cleaned text (shorter = broader net for semantic variants)
4. `call_manager.execute(search_recent(search_phrase))` → raw_tweets
5. `matcher.find_matches(full_query_text, raw_tweets)` → matched

**PROFILING**
- `get_users_batch(unique_accounts)` — cache-first (populated by search_recent includes)
- `scorer.compute_bot_score(profile)` for each
- **All matched accounts proceed** — bot_score is a signal, not a gate

**EXPANDING**
- Fetch tweet histories for top suspects (sorted by bot_score, capped by depth config)
- Cache-first: skip if `tweets_fetched_at` is fresh
- Roles: `ORIGIN` (earliest matched tweet), `AMPLIFIER` (bot_score ≥ 0.6), `SUSPECTED` (everyone else)

**ANALYZING**
- `analyzer.detect_burst_window()` — O(n) two-pointer sliding window
- `analyzer.classify_pattern()` → COORDINATED_INAUTHENTIC / BURST_AMPLIFICATION / BOT_NETWORK / ORGANIC_AMPLIFICATION / INCONCLUSIVE
- `analyzer.compute_confidence()` → 0.0–1.0
- Verdict: COORDINATED (>0.6), UNCERTAIN (>0.3), ORGANIC (≤0.3)

### Matching tiers (matcher.py)
| Type | Metric | Threshold |
|------|--------|-----------|
| EXACT | string equality | 1.0 |
| FUZZY | max(fuzz.ratio, fuzz.token_set_ratio) | ≥ 0.80 |
| SEMANTIC | token_set_ratio only | ≥ 0.65 |

`elif` prevents double-flagging. SEMANTIC = deliberate rewrite, more suspicious than FUZZY.

### Bot score signals (scorer.py)
Account age, following/followers ratio, default_profile_img, no description, tweet_rate (>50/day = +0.20, >20/day = +0.10).

### API call management (call_manager.py)
- 15-min rate limit windows per endpoint
- Monthly budget cap (tracked in `api_call_log`)
- `log_call()` for cache hits (cache_hit=1, doesn't count against budget)

### X client (x_client.py)
- `search_recent(query)` — wraps query in quotes, truncates to 200 chars (prevents boolean operator conflicts)
- `get_tweet_by_id(tweet_id)` — resolves URL input to tweet text
- `get_users_batch(user_ids)` — cache-first from `_user_cache` populated by search includes
- `get_user_tweets(user_id)` — timeline fetch for EXPANDING

### DB (queries.py / schema.sql)
Key tables: `accounts`, `tweets`, `investigations`, `cell_members`, `tweet_matches`, `api_call_log`
Key view: `account_investigation_summary` — investigation_count, times_as_origin, last_seen_at per account
`text_hash` = MD5 of normalised (lowercase, stripped, collapsed whitespace) tweet text

### SSE streaming (api/investigations.py)
- POST `/investigations` → creates DB row, starts background task, returns `investigation_id`
- GET `/investigations/{id}/stream` → EventSource, per-investigation `asyncio.Queue`
- `_run_and_cleanup` wrapper ensures queue is removed on completion or failure
- `TERMINAL_STAGES = {"COMPLETE", "FAILED"}`

---

## Frontend architecture

### Component tree
```
App
├── BudgetBar          — API call counter (top bar)
├── InputPanel         — textarea + QUICK/STANDARD/DEEP pills + Investigate button
├── ProgressStream     — SSE stage messages during pipeline
├── ReportView         — shown when status === 'COMPLETE' && report != null
│   ├── CytoscapeGraph — force-directed graph (CDN Cytoscape, cose layout)
│   ├── BurstTimeline  — SVG bar chart of tweet volume over time
│   ├── AccountList    — sortable cell member table
│   └── MutationVariants — copy-paste variants + semantic rewrites, deduped by text
└── PastInvestigations — list of prior investigations, click to reload
```

### Key hooks
- `useSSE(url, onEvent)` — EventSource wrapper, cleans up on url change
- `useInvestigation()` — full lifecycle: POST → SSE → GET report
  - `TERMINAL = new Set(['COMPLETE', 'FAILED'])`
  - On COMPLETE: fetches `/investigations/{id}` for full report
  - On fetch failure: sets status to FAILED with message

### Graph (CytoscapeGraph.jsx)
- Nodes sized by match_count, coloured by role (ORIGIN=red, AMPLIFIER=amber, SUSPECTED=grey)
- Edges: spoke pattern, origin → any account with `match_type !== 'EXACT'` (includes SEMANTIC)
- `react({ strictMode: false })` in vite.config.js — prevents Cytoscape double-init

### MutationVariants
- Two sections: "Copy-paste variants" (FUZZY) and "Semantic rewrites" (SEMANTIC)
- Deduped by text — shows first poster's handle + "+N others"
- Badge colours: red (≥0.90 FUZZY), amber (<0.90 FUZZY), purple (SEMANTIC)
- Legend line under each section title explains the tier

---

## Known design decisions & why

| Decision | Reason |
|----------|--------|
| 6-word prefix for search phrase | Shorter = broader net; catches semantic rewrites that diverge after the opening phrase |
| All matched accounts are suspects | Bot score is a signal not a gate; real ops use normal-looking accounts |
| SEMANTIC tier at 0.65 via token_set_ratio only | Character-level ratio undersells rewrites; token_set measures shared vocabulary regardless of structure |
| Cytoscape from CDN | npm bundle caused double-init issues in React StrictMode |
| `max(ratio, token_set_ratio)` for FUZZY | Catches both near-copies and reordered text; `elif` prevents double-counting |

## Known deferred work (not yet prioritised)
- **Origin detection**: `detect_origin` picks earliest timestamp — can misfire on "cheerleader" reply fragments that happen to match. Needs more investigation data before tuning.
- **Repeat offenders UI**: `get_repeat_offenders()` exists in queries.py but not surfaced in frontend
- **`narratives` / `investigation_narratives` tables**: scaffolded in schema, not yet used
