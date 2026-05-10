# Clean Your Feed — Figma Design Spec

## Product summary
An OSINT/journalism tool that investigates coordinated inauthentic behaviour on X (Twitter). Users paste a tweet URL or text → a pipeline searches the X API → scores accounts → classifies a "coordination cell" → renders a full report. Think: investigative newsroom dashboard, not a social media product.

## Desired aesthetic direction
**Current**: Minimal newspaper (Georgia serif headlines, monochrome, hairline borders, uppercase labels).
**Target**: More graphic/investigative — think threat intelligence dashboards, long-form data journalism (NYT, The Intercept, Bellingcat). Should feel like a tool a journalist or analyst would trust with serious work. Dark mode optional but the investigative feel should come from density, information hierarchy, and purposeful use of the alert colour system — not decoration.

---

## Design tokens

### Colours
| Token | Hex | Use |
|-------|-----|-----|
| `--bg` | `#FAFAF8` | Page background |
| `--surface` | `#FFFFFF` | Card/input backgrounds |
| `--surface-alt` | `#F4F4F0` | Alternating rows, disabled states |
| `--border` | `#E5E5E0` | All hairline dividers |
| `--text-primary` | `#1A1A1A` | Body, headlines |
| `--text-secondary` | `#6B6B6B` | Labels, metadata |
| `--text-muted` | `#9B9B9B` | Placeholder, timestamps |
| `--text-ghost` | `#AFAFAB` | Placeholder text, minor UI |
| `--alert-red` | `#C0392B` | COORDINATED verdict, ORIGIN role, near-exact match, danger |
| `--alert-amber` | `#E67E22` | UNCERTAIN verdict, AMPLIFIER role, FUZZY match |
| `--alert-green` | `#27AE60` | ORGANIC verdict |
| `--alert-purple` | `#6C3483` | SEMANTIC match (human rewrite — most suspicious type) |

### Typography
| Role | Font | Size | Weight | Transform | Tracking |
|------|------|------|--------|-----------|---------|
| Verdict headline | Georgia / serif | 52px | 700 | none | -0.02em |
| Section heading in Top Finds | Georgia / serif | 22px | 700 | none | -0.02em |
| Body / table rows | System UI | 13–15px | 400 | none | — |
| Label / column header | System UI | 9px | 600 | UPPERCASE | 0.14em |
| Button / badge | System UI | 9–12px | 600 | UPPERCASE | 0.06–0.10em |
| Stage message (progress) | Monospace | 12px | 400 | none | — |

### Spacing
- Container max-width: **960px**, centered, `padding: 40px 24px 80px`
- Section gap: **40px**
- Grid column gap (report split): **40px**
- Card/table cell padding: **8–12px**

---

## Layout structure

```
┌─────────────────────────────────────────────────────────┐
│ Budget Bar (sticky, 32px)                                │
│  "API calls this month: 22 / 10,000 (0.2%)"  [bar]      │
├─────────────────────────────────────────────────────────┤
│ Tab Bar (sticky, below budget bar)                       │
│  [ Investigate ]  [ Top Finds ]                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ── INVESTIGATE TAB ──────────────────────────────────   │
│                                                          │
│  InputPanel                                              │
│    [textarea: "Paste tweet URL or text…"]                │
│    [QUICK] [STANDARD] [DEEP]   ← depth pills            │
│    [INVESTIGATE]               ← full-width CTA          │
│                                                          │
│  ProgressStream (while running)                          │
│    ● SEARCHING   Searching for matching tweets…          │
│    ● PROFILING   Scored 9 accounts (1 high bot-score)    │
│    ● EXPANDING   Fetching histories 3/9                  │
│    ● ANALYZING   Computing burst window…                 │
│                                                          │
│  ReportView (on complete)                                │
│    ┌──────────────────┬──────────────────────────────┐  │
│    │ COORDINATED      │  [Network graph — Cytoscape] │  │
│    │ (52px serif red) │   Force-directed, nodes are  │  │
│    │                  │   accounts, edges = matched  │  │
│    │ Cell size: 11    │   tweet relationship         │  │
│    │ Burst window:58m │                              │  │
│    │ Confidence: 0.74 │   Node colours:              │  │
│    │ Pattern: ORGANIC │   ORIGIN = red               │  │
│    │ Origin: @rdd147  │   AMPLIFIER = amber          │  │
│    │ API calls: 8     │   SUSPECTED = grey           │  │
│    │                  │   Node size ∝ match_count    │  │
│    │ [Mute list]      │   (20–60px diameter, 8px/match)│ │
│    └──────────────────┴──────────────────────────────┘  │
│                                                          │
│    [Tweet Volume Over Time]   ← SVG bar chart            │
│    [Cell Members]             ← sortable table           │
│    [Coordination Variants]    ← FUZZY list               │
│    [Semantic Rewrites]        ← SEMANTIC list            │
│                                                          │
│  ── TOP FINDS TAB ────────────────────────────────────   │
│                                                          │
│  Top Investigations                                      │
│  Ranked by confidence — highest coordination signal first│
│  [All] [COORDINATED] [UNCERTAIN] [ORGANIC]               │
│  [Ranked table, 10 per page, Load more]                  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Component inventory

### 1. BudgetBar
**Position**: Sticky top, 32px tall
**Content**: `"API calls this month: {N} / 10,000 ({pct}%)"` + linear progress bar
**Bar**: max-width 180px, 3px tall, fill colour `--alert-red` at 45% opacity, 100% opacity when >80%
**Data range**: N = 0–10,000 (monthly X API call budget)

### 2. InputPanel
**Textarea**: 96px min-height, 15px text, placeholder = `"Paste a tweet URL or tweet text…"`
**Depth pills**: 3 options — `QUICK` / `STANDARD` / `DEEP` (selected = 1px border `--text-primary`)
- QUICK: max 5 expansions, 5 API calls
- STANDARD: 10 expansions, 30 API calls
- DEEP: 20 expansions, 100 API calls
**CTA button**: Full width, filled black, uppercase, `INVESTIGATE` / `INVESTIGATING…` (disabled state)

### 3. ProgressStream
**Stages** (enum, in order): `SEARCHING` → `PROFILING` → `EXPANDING` → `ANALYZING` → `COMPLETE`
**Side states**: `FAILED` (red dot), `PARTIAL` (amber dot — some expansions failed but continued)
**Stage dot states**: active = black, complete = `#C8C8C4`, partial = amber, failed = red
**Messages are free text** emitted during each stage, shown in monospace 12px

### 4. ReportView — left column metrics
All metrics come from the `investigations` DB table:

| Metric | Type | Example values |
|--------|------|----------------|
| `verdict` | enum | `COORDINATED` / `UNCERTAIN` / `ORGANIC` |
| `confidence` | float 0.0–1.0 | 0.74 (displayed as 0.74, not %) |
| `cell_size` | integer | 3–20+ accounts |
| `burst_window_s` | integer seconds | displayed as minutes (e.g. 58 min, 2 hrs) |
| `pattern_type` | enum | `COORDINATED_INAUTHENTIC` / `BURST_AMPLIFICATION` / `BOT_NETWORK` / `ORGANIC_AMPLIFICATION` / `INCONCLUSIVE` |
| `origin_account` | string (handle) | `@rdd147` — links to x.com/{handle} |
| `api_calls_used` | integer | 5–100 |

**Verdict headline** colour mapping:
- COORDINATED → `#C0392B` (red)
- UNCERTAIN → `#E67E22` (amber)
- ORGANIC → `#27AE60` (green)

**Mute list export**: two buttons — "Copy to clipboard" / "Download .txt" — exports `@handle\n@handle…`

### 5. CytoscapeGraph (network graph)
**Library**: Cytoscape.js (CDN), force-directed layout (`cose`)
**Container**: 100% × 420px, 1px border `--border`
**Nodes**:
- Diameter: `20 + match_count * 8`, clamped 20–60px
- Colour by role: ORIGIN=`#C0392B`, AMPLIFIER=`#E67E22`, SUSPECTED=`#95A5A6`
- Label: `@handle` truncated to 13 chars, 10px sans-serif, below node
- Selected state: 3px solid `#1A1A1A` border ring
**Edges**: spoke pattern, origin node → all accounts with any FUZZY or SEMANTIC match (not EXACT)
- Line colour: `#E5E5E0`, 1px, bezier curve
**Interaction**: tap node → highlights it + scrolls account table to that row

### 6. BurstTimeline (SVG bar chart)
**Type**: SVG vertical bar chart, 5-minute buckets
**Dimensions**:
- Chart area: 112px tall
- Bar width: 4px, gap: 2px (6px per bucket)
- Padding: left 28px, bottom 32px, top 8px, right 16px
- Labels: `HH:MM` (UTC), 45° rotated, shown every `max(2, ceil(n/6))` buckets
- Y axis: 0 and max count only
**Bars**: fill `#1A1A1A`, height proportional to count/maxCount
**Burst marker**: dashed red vertical line (`#C0392B`, 1px, dash 3px gap 3px) positioned at bucket before the peak
**Data source**: `tweet_matches.posted_at` (Unix timestamps), all match types

### 7. AccountList (table)
**Columns**: Handle | Role | Bot Score | Seen In | Matches
**Handle**: `@username`, clickable — syncs with graph highlight
**Role badge** (enum): `ORIGIN` (red) / `AMPLIFIER` (amber) / `SUSPECTED` (grey)
**Bot score**: 0.0–1.0, displayed as inline bar (56px × 3px, fill `#C0392B`) + numeric `0.00`
**Seen in**: integer (investigations this account appeared in) — highlighted bold red if ≥3 ("repeat offender")
**Matches**: integer (matching tweets this account contributed)
**Row states**: alternating bg `#FAFAF8` / `#F4F4F0`, selected = left 3px red border

### 8. MutationVariants (two sections)
**Section A: "Copy-paste variants"** — match_type = FUZZY
- Badge: ≥90% → red `near-exact`, 80–90% → amber `variant`
- Content: raw tweet text + handle + "+N others" if multiple accounts posted same text

**Section B: "Semantic rewrites"** — match_type = SEMANTIC
- Badge: purple, score shown as % (e.g. 69.0%)
- Note: "same vocabulary, restructured — human editorial effort to evade duplicate detection"
- These are MORE suspicious than FUZZY because they show deliberate evasion

**Similarity score ranges**:
- EXACT = 1.0 (not shown here, counted in match totals)
- FUZZY = 0.80–1.0 (max of character-ratio and token-set-ratio)
- SEMANTIC = 0.65–0.79 (token-set-ratio only)

### 9. TopFinds (discovery tab)
**Table columns**: # | Verdict | Seed text (72 chars) | Confidence bar+% | Cell | Pattern | Origin | Date | Explore
**Confidence bar**: 4px tall, colour: red ≥60%, amber 30–60%, grey <30%
**Filter pills**: All / COORDINATED / UNCERTAIN / ORGANIC
**Pagination**: 10 rows per page, "Load more" appends next page
**Explore button**: loads full report + switches to Investigate tab

---

## Colour system summary (semantic)

```
RED    #C0392B  →  danger / coordination confirmed / ORIGIN / near-exact copy
AMBER  #E67E22  →  warning / uncertain / AMPLIFIER / deliberate variation
GREEN  #27AE60  →  safe / organic / no coordination detected
PURPLE #6C3483  →  intel / semantic rewrite / most sophisticated evasion
GREY   #95A5A6  →  neutral / SUSPECTED / unknown
```

## What the tool is NOT
- Not a social media viewer — no profile photos, no like counts, no follower lists
- Not real-time — results are a snapshot from the X API 7-day recent search window
- Not automated — user drives every investigation manually

## Suggested redesign priorities for Figma agent
1. **Report view**: The 40/60 split (metrics left, graph right) works but the graph dominates; consider giving the metrics more visual weight — the verdict headline should be the first thing you read
2. **BurstTimeline**: Currently a thin SVG bar chart. Could be much more dramatic — wider, with a shaded "burst zone" behind the bars, and an annotation pin at the peak
3. **AccountList**: Table is functional but cold. Could add a small inline spark for bot score, clearer role colour coding per row
4. **Network graph**: The Cytoscape default style is generic. The key insight is the spoke pattern (everyone connects to origin) — emphasise the ORIGIN node visually (larger, labelled differently)
5. **Progress stream**: Currently a plain list of dots. Could be a more cinematic step-through — the pipeline stages are: SEARCHING → PROFILING → EXPANDING → ANALYZING → COMPLETE
