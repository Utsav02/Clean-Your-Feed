# Clean Your Feed

A local-first investigative journalism tool for detecting coordinated inauthentic behaviour on X (Twitter).

Paste a tweet URL, a reply thread, or a list of handles → the pipeline searches X, scores accounts, detects coordination cells, and renders a structured evidence report — with zero database queries served to anyone but you.

> **PoC / local-only stage.** Architecture is intentionally naive: single-user, SQLite, no auth, no deployment. The goal right now is investigative utility, not production readiness. Everything runs on your laptop.

---

## What it investigates

| Mode | Input | What it finds |
|------|-------|---------------|
| **Tweet / URL** | Tweet text or `x.com` URL | Accounts spreading the same or semantically rewritten narrative |
| **Replies** | Tweet URL | Reply section analysed for coordinated pile-ons |
| **Profiles** | `@handle` list | Cross-profile timeline comparison for shared targets, themes, and posting patterns |

---

## Example investigations (from local DB)

### 1 — Vancouver mayoral candidate harassment cell
**Mode:** Replies · **Verdict:** COORDINATED · **Confidence:** 64.7% · **Cell:** 8 accounts · **Depth:** DEEP

8 accounts with 80–100% reply ratios were found targeting `@kareemformayor` across multiple tweet threads. 4 of the 8 were created in coordinated pairs (Jul 2025 and Oct 2025). The evidence panel surfaced 12 direct attack tweets stored in the DB, including:

```
@themoney604      → "Can't balance your diet. Probably can't do a budget. Go home"
@Frank9941541571  → "Don't forget, corrupt also."
@anthony21536696  → "Indian supremicists in bc"
@roy17391         → "Liberal faggets 😂"
```

`@themoney604`: 0 followers, 8 total tweets in its entire history — a weapon account created and held dormant for 9 months before deployment. `@anthony21536696`: 33.8 tweets/day since creation (Feb 2026), 97% reply ratio, self-repeated "Indian supremacy" across 34 separate conversations targeting BC journalists and Indigenous rights advocates.

Shared target list included `@kareemformayor` (all 8 accounts), `@matt_kercher`, `@terrilltf`, `@vancouversun`, and 16 other Vancouver political/media figures.

---

### 2 — Pilot rescue narrative amplification cell
**Mode:** Tweet · **Verdict:** COORDINATED · **Confidence:** 77.1% · **Cell:** 10 accounts · **Depth:** STANDARD

A story about a rescue pilot walking 110 miles spread as an exact copy-paste across 10 accounts within a 58-minute burst window. The full query text and a 6-word search prefix both returned matches, confirming the narrative was being seeded deliberately rather than organically shared.

---

### 3 — Zomato boycott coordination (India)
**Mode:** Tweet · **Verdict:** COORDINATED · **Confidence:** 63.0% · **Cell:** 4 accounts · **Depth:** DEEP

Identical text — *"Cancelling my Order right now. BSDK @zomato uninstalling your app also"* — spread verbatim across 4 accounts after `@HindutvaDon_` (15K followers, 1.4M views) posted a screenshot of a Muslim delivery partner's name. `@_Thynker_` posted the tweet twice: once standalone, once as a reply to the origin. Bot scores for all accounts were 0.0–0.2, confirming real-human coordinated amplification rather than automation.

This case illustrates the tool's core distinction: **ORGANIC_AMPLIFICATION** (real people making a coordinated choice) vs **BOT_NETWORK** (automated infrastructure). Both are detected; the evidence differs.

---

### 4 — BC profile comparison (9 accounts)
**Mode:** Profiles · **Verdict:** COORDINATED · **Confidence:** 74.3% · **Cell:** 9 accounts · **Depth:** STANDARD

`@Snake1633691791`, `@GlugSnurf`, and 7 others compared by timeline. Shared targets and thematic clusters surfaced without any additional API calls — all analysis ran against tweets already stored from the EXPANDING phase.

---

## How it works

```
Input (URL / text / handles)
        ↓
    SEARCHING — search_recent or search_replies via X API / twscrape scraper
        ↓
    PROFILING — score each account (age, ratio, default img, tweet rate, numeric suffix)
        ↓
    EXPANDING — fetch tweet histories for top suspects
        ↓
    ANALYZING — burst window detection, pattern classification, coordination score
        ↓
    COMPLETE  — SSE stream closes, report loaded from DB
```

**Three matching tiers** (matcher.py):

| Type | Method | Threshold | Meaning |
|------|--------|-----------|---------|
| EXACT | string equality | 1.0 | Copy-paste |
| FUZZY | RapidFuzz ratio + token_set_ratio | ≥ 0.80 | Near-copy |
| SEMANTIC | token_set_ratio only | ≥ 0.65 | Deliberate rewrite |

SEMANTIC matches are more suspicious than FUZZY — they indicate conscious rewording to evade detection while preserving the narrative.

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + aiosqlite + httpx + RapidFuzz (Poetry, Python 3.13) |
| Frontend | React + Vite, Cytoscape.js (CDN), SVG charts hand-rolled |
| Database | SQLite at `data/feed_cleaner.db` |
| X data | X API v2 (pay-as-you-go) + optional twscrape scraper pool |

---

## Report panels

After an investigation completes, the report is tab-driven. Select one or more panels; multiple selections stack:

| Tab | What it shows |
|-----|---------------|
| **Network Graph** | Force-directed graph — nodes sized by match count, coloured by role |
| **Tweet Volume** | SVG bar chart of tweet activity over the burst window |
| **Copy Variants** | FUZZY and SEMANTIC match groups, deduped by text |
| **Evidence** | Per-account dossiers: tweet velocity, weapon-account flags, repeated phrases, direct attacks on seed author |
| **Profile Analysis** | Cell coordination score (0–100), timing signals, shared targets, historical themes |

---

## Licence

Personal research tool. Not licensed for redistribution or commercial use at this stage.
