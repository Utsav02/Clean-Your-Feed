"""
API Call Manager — cache-first pattern.

Order of operations for every real API call:
  1. Check cache (TTL per resource type)
  2. Check rate-limit window (per endpoint, 15-minute sliding window)
  3. Check monthly budget
  4. Make the API call (delegated to caller)
  5. Log the call

This module exposes helpers that the pipeline uses before and after each call.
It does NOT make the calls itself — the pipeline passes the coroutine to execute.
"""

import time
from typing import Callable, Awaitable, Any

from backend import config
from backend.db import queries

# Cache TTLs in seconds
CACHE_TTL = {
    "account_profile": 7 * 24 * 3600,  # 7 days
    "tweet_history": 24 * 3600,         # 24 hours
}

# Rate limits: max real calls per 15-minute window per endpoint
RATE_LIMITS = {
    "search_recent": 10,
    "search_replies": 10,
    "get_users_batch": 15,
    "get_users_by_usernames": 15,
    "get_user_tweets": 15,
}


class RateLimitError(Exception):
    pass


class BudgetExceededError(Exception):
    pass


async def calls_this_month(db_path: str) -> int:
    return await queries.count_calls_this_month(db_path)


async def calls_this_window(db_path: str, endpoint: str) -> int:
    return await queries.count_calls_this_window(db_path, endpoint)


async def budget_remaining(db_path: str) -> dict:
    used = await calls_this_month(db_path)
    remaining = max(0, config.MONTHLY_BUDGET - used)
    pct = round(used / config.MONTHLY_BUDGET * 100, 1) if config.MONTHLY_BUDGET else 0
    return {
        "used": used,
        "remaining": remaining,
        "total": config.MONTHLY_BUDGET,
        "pct": pct,
    }


async def log_call(
    db_path: str,
    endpoint: str,
    investigation_id: int | None = None,
    cache_hit: bool = False,
) -> None:
    await queries.log_api_call(db_path, endpoint, investigation_id, cache_hit)


async def execute(
    db_path: str,
    endpoint: str,
    fn: Callable[[], Awaitable[Any]],
    investigation_id: int | None = None,
) -> Any:
    """
    Execute an API call with rate-limit and budget checks.

    Raises RateLimitError or BudgetExceededError before making the call.
    Always logs the call (cache_hit=False) on success.
    """
    window_count = await calls_this_window(db_path, endpoint)
    limit = RATE_LIMITS.get(endpoint, 15)
    if window_count >= limit:
        raise RateLimitError(
            f"Rate limit reached for {endpoint}: {window_count}/{limit} in the last 15 min"
        )

    month_count = await calls_this_month(db_path)
    if month_count >= config.MONTHLY_BUDGET:
        raise BudgetExceededError(
            f"Monthly budget exhausted: {month_count}/{config.MONTHLY_BUDGET}"
        )

    result = await fn()
    await log_call(db_path, endpoint, investigation_id, cache_hit=False)
    return result


def is_profile_stale(profile_fetched_at: int | None) -> bool:
    if profile_fetched_at is None:
        return True
    return (time.time() - profile_fetched_at) > CACHE_TTL["account_profile"]


def is_tweet_history_stale(tweets_fetched_at: int | None) -> bool:
    if tweets_fetched_at is None:
        return True
    return (time.time() - tweets_fetched_at) > CACHE_TTL["tweet_history"]
