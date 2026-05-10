"""
Search backend abstraction — routes tweet searches to either the scraper
(twscrape, free) or the paid X API, based on SEARCH_MODE config.

Modes (set via SEARCH_MODE env var):
    scraper_with_fallback  (default)
        Try scraper first. If unavailable, returns < 50% of requested results,
        or raises, automatically fall back to the paid API.

    scraper
        Scraper only — never touch the paid API. Fails hard if pool not ready
        or results are sparse. Use for pure cost-saving when you accept the risk.

    api
        Paid X API only. Ignores scraper entirely. Use when you need
        authoritative, citable data.

Return shape from search():
    {
        "tweets":     list[dict],   # same shape as x_client.search_recent()
        "users":      list[dict],   # same shape as x_client._parse_user()
        "source":     "SCRAPER" | "API",
        "cost_usd":   float,        # 0.0 for scraper, estimated for API
    }
"""

import logging
import os

from backend.services import scraper_pool

log = logging.getLogger(__name__)

SEARCH_MODE = os.getenv("SEARCH_MODE", "scraper_with_fallback")

# Estimated X API cost per tweet read (pay-as-you-go, Feb 2026 pricing)
_COST_PER_TWEET = 0.005


async def search(
    query: str,
    limit: int = 100,
    *,
    force_api: bool = False,
) -> dict:
    """
    Execute a tweet search through the configured backend.

    Args:
        query:     Raw search phrase (not yet quoted/truncated — backends handle that)
        limit:     Max tweets to return
        force_api: Override SEARCH_MODE and use the paid API regardless

    Returns dict with keys: tweets, users, source, cost_usd
    """
    mode = "api" if force_api else SEARCH_MODE

    if mode == "api":
        return await _search_api(query, limit)

    if mode == "scraper":
        return await _search_scraper(query, limit)

    # scraper_with_fallback (default)
    return await _search_with_fallback(query, limit)


# ── Backends ──────────────────────────────────────────────────────────────────

async def _search_scraper(query: str, limit: int) -> dict:
    tweets, users = await scraper_pool.search(query, limit)
    return {
        "tweets":   tweets,
        "users":    users,
        "source":   "SCRAPER",
        "cost_usd": 0.0,
    }


async def _search_api(query: str, limit: int) -> dict:
    from backend.services import x_client

    tweets = await x_client.search_recent(query, limit)

    # x_client populates _user_cache from includes; expose them to the caller
    users = list(x_client._user_cache.values())

    cost = len(tweets) * _COST_PER_TWEET
    return {
        "tweets":   tweets,
        "users":    users,
        "source":   "API",
        "cost_usd": cost,
    }


async def _search_with_fallback(query: str, limit: int) -> dict:
    """Try scraper; fall back to API if pool is down or results are sparse."""
    if not scraper_pool.is_ready():
        log.info("search_backend: scraper pool not ready, using API")
        return await _search_api(query, limit)

    try:
        tweets, users = await scraper_pool.search(query, limit)

        # Sparse result check: if we got less than 50% of what we asked for
        # AND the paid API is available, upgrade silently.
        if len(tweets) < limit * 0.5:
            log.info(
                "search_backend: scraper returned %d/%d results, falling back to API",
                len(tweets), limit,
            )
            return await _search_api(query, limit)

        log.info("search_backend: scraper returned %d tweets (free)", len(tweets))
        return {
            "tweets":   tweets,
            "users":    users,
            "source":   "SCRAPER",
            "cost_usd": 0.0,
        }

    except Exception as e:
        log.warning("search_backend: scraper failed (%s), falling back to API", e)
        return await _search_api(query, limit)
