"""
Scraper account pool built on twscrape.

Accounts are configured via the SCRAPER_ACCOUNTS environment variable:
    SCRAPER_ACCOUNTS=handle1:pass1:email1:emailpass1,handle2:pass2:...

The pool is a singleton initialised at startup. If SCRAPER_ACCOUNTS is empty
or all accounts fail login the pool is unavailable and callers should fall
back to the paid API.

Tweet dicts returned by search() match the shape produced by x_client.py so
the rest of the pipeline (matcher, scorer, investigator) requires no changes:
    {
        "id":        str,
        "author_id": str,
        "text":      str,
        "posted_at": int | None,   # Unix timestamp
        "lang":      str | None,
        "is_reply":  bool,
    }

User dicts match _parse_user() in x_client.py.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from twscrape import AccountsPool, API, gather
from twscrape.logger import set_log_level

log = logging.getLogger(__name__)

# Suppress twscrape's verbose internal logging; keep warnings/errors
set_log_level("WARNING")

# ── Singleton state ──────────────────────────────────────────────────────────

_pool: AccountsPool | None = None
_api:  API | None = None
_ready = False          # True once at least one account logged in successfully
_init_lock = asyncio.Lock()

# Separate SQLite file for scraper account cookies (never the main DB)
_POOL_DB = "data/scraper_accounts.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_env_accounts() -> list[tuple[str, str, str, str]]:
    """
    Parse SCRAPER_ACCOUNTS env var.
    Format: handle:password:email:email_password  (comma-separated entries)
    Returns list of (handle, password, email, email_password) tuples.
    """
    raw = os.getenv("SCRAPER_ACCOUNTS", "").strip()
    if not raw:
        return []
    accounts = []
    for entry in raw.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 4:
            accounts.append(tuple(parts))
        else:
            log.warning("SCRAPER_ACCOUNTS: skipping malformed entry (expected 4 colon-separated fields): %s", entry)
    return accounts


def _ts(dt) -> int | None:
    """Convert a datetime (or None) to a Unix int."""
    if dt is None:
        return None
    if isinstance(dt, (int, float)):
        return int(dt)
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _tweet_to_dict(tw) -> dict:
    """Convert a twscrape Tweet object to our standard tweet dict shape."""
    return {
        "id":        str(tw.id),
        "author_id": str(tw.user.id) if tw.user else str(getattr(tw, "author_id", "")),
        "text":      tw.rawContent or tw.content or "",
        "posted_at": _ts(tw.date),
        "lang":      getattr(tw, "lang", None),
        "is_reply":  bool(getattr(tw, "inReplyToTweetId", None)),
    }


def _user_to_dict(u) -> dict:
    """Convert a twscrape User object to our standard user dict shape."""
    img_url = str(u.profileImageUrl or "")
    return {
        "id":                  str(u.id),
        "handle":              u.username or "",
        "display_name":        u.displayname or "",
        "created_at":          _ts(u.created),
        "followers":           u.followersCount,
        "following":           u.friendsCount,
        "tweet_count":         u.statusesCount,
        "verified":            bool(u.verified or u.blue),
        "default_profile_img": "default_profile" in img_url,
        "description":         u.rawDescription or u.description or None,
        "profile_fetched":     True,
    }


# ── Initialisation ────────────────────────────────────────────────────────────

async def init_pool() -> bool:
    """
    Called once at app startup. Loads accounts from env, logs in,
    and marks the pool ready if at least one account is usable.
    Returns True if pool is ready, False if no accounts configured or all failed.
    """
    global _pool, _api, _ready

    async with _init_lock:
        if _pool is not None:
            return _ready

        accounts = _parse_env_accounts()
        if not accounts:
            log.info("SCRAPER_ACCOUNTS not set — scraper pool disabled, using paid API only")
            _pool = None
            _ready = False
            return False

        import os as _os
        _os.makedirs("data", exist_ok=True)

        _pool = AccountsPool(_POOL_DB)
        _api  = API(_pool)

        added = 0
        for handle, password, email, email_password in accounts:
            try:
                await _pool.add_account(handle, password, email, email_password)
                added += 1
            except Exception as e:
                log.warning("scraper_pool: failed to add account @%s: %s", handle, e)

        if added == 0:
            log.warning("scraper_pool: no accounts added — pool disabled")
            _ready = False
            return False

        # Login all accounts (skips accounts already logged in / cookie-fresh)
        try:
            await _pool.login_all()
        except Exception as e:
            log.warning("scraper_pool: login_all error: %s", e)

        # Check at least one account is active
        pool_accounts = await _pool.get_all()
        active = [a for a in pool_accounts if a.active]
        if not active:
            log.warning("scraper_pool: no active accounts after login — pool disabled")
            _ready = False
            return False

        log.info("scraper_pool: ready with %d active account(s)", len(active))
        _ready = True
        return True


def is_ready() -> bool:
    return _ready


# ── Public search interface ───────────────────────────────────────────────────

async def search(query: str, limit: int = 100) -> tuple[list[dict], list[dict]]:
    """
    Search recent tweets using the scraper account pool.

    Returns (tweets, users) where both lists use the same dict shapes
    as x_client.py — drop-in compatible with the existing pipeline.

    Raises RuntimeError if pool is not ready.
    Raises twscrape.NoAccountError if all accounts are rate-limited.
    """
    if not _ready or _api is None:
        raise RuntimeError("Scraper pool is not ready")

    phrase = query[:200].replace('"', "'")
    # Mirror x_client.py: phrase-match, exclude retweets, English only
    search_query = f'"{phrase}" -is:retweet lang:en'

    raw_tweets = await gather(_api.search(search_query, limit=limit))

    tweets = []
    users  = {}
    for tw in raw_tweets:
        tweets.append(_tweet_to_dict(tw))
        if tw.user and str(tw.user.id) not in users:
            users[str(tw.user.id)] = _user_to_dict(tw.user)

    return tweets, list(users.values())


async def get_user_by_handle(handle: str) -> dict | None:
    """
    Look up a single user by handle. Returns user dict or None.
    """
    if not _ready or _api is None:
        raise RuntimeError("Scraper pool is not ready")
    try:
        handle = handle.lstrip("@")
        user = await _api.user_by_login(handle)
        return _user_to_dict(user) if user else None
    except Exception as e:
        log.warning("scraper_pool.get_user_by_handle @%s: %s", handle, e)
        return None


async def get_user_tweets(user_id: str, limit: int = 100) -> list[dict]:
    """
    Fetch a user's recent tweets by user ID. Returns list of tweet dicts.
    """
    if not _ready or _api is None:
        raise RuntimeError("Scraper pool is not ready")
    try:
        raw = await gather(_api.user_tweets(int(user_id), limit=limit))
        return [_tweet_to_dict(tw) for tw in raw]
    except Exception as e:
        log.warning("scraper_pool.get_user_tweets %s: %s", user_id, e)
        return []
