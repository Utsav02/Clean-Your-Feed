"""
Real X API v2 client using httpx.AsyncClient.

Return shapes are identical to the stubs so the pipeline requires no changes.
Users fetched as includes in search_recent are cached in _user_cache so that
get_users_batch can serve them without a second API call.
"""

import os
from datetime import datetime, timezone

import httpx

from backend.services.call_manager import RateLimitError

_BASE_URL = "https://api.twitter.com/2"

# Populated by search_recent from the includes block; read by get_users_batch.
_user_cache: dict[str, dict] = {}


# ── Auth ────────────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    token = os.environ.get("X_BEARER_TOKEN", "")
    if not token:
        raise ValueError("X_BEARER_TOKEN environment variable is not set")
    return {"Authorization": f"Bearer {token}"}


# ── Response helpers ─────────────────────────────────────────────────────────

def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise ValueError("Invalid or expired X API bearer token")
    if response.status_code == 429:
        raise RateLimitError("X API rate limit hit")
    if response.status_code >= 400:
        raise ValueError(f"X API error {response.status_code}: {response.text}")


def _ts(iso: str | None) -> int | None:
    """Parse an ISO-8601 string (with or without trailing Z) to a Unix int."""
    if not iso:
        return None
    try:
        return int(
            datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        )
    except (ValueError, AttributeError):
        return None


# ── Parsers ──────────────────────────────────────────────────────────────────

def _parse_user(u: dict) -> dict:
    metrics  = u.get("public_metrics", {})
    img_url  = u.get("profile_image_url", "") or ""
    return {
        "id":                  u["id"],
        "handle":              u.get("username", ""),
        "display_name":        u.get("name", ""),
        "created_at":          _ts(u.get("created_at")),
        "followers":           metrics.get("followers_count"),
        "following":           metrics.get("following_count"),
        "tweet_count":         metrics.get("tweet_count"),
        "verified":            bool(u.get("verified", False)),
        "default_profile_img": "default_profile" in img_url,
        "description":         u.get("description"),
        "profile_fetched":     True,
    }


def _parse_tweet(t: dict, author_id: str | None = None) -> dict:
    return {
        "id":        t["id"],
        "author_id": author_id or t.get("author_id", ""),
        "text":      t.get("text", ""),
        "posted_at": _ts(t.get("created_at")),
        "lang":      t.get("lang"),
        # Present when tweet.fields includes in_reply_to_user_id
        "is_reply":  bool(t.get("in_reply_to_user_id")),
    }


# ── Public API ───────────────────────────────────────────────────────────────

async def search_recent(query: str, max_results: int = 100) -> list[dict]:
    """
    GET /2/tweets/search/recent

    Appends "-is:retweet lang:en" to the query.
    Caches user objects from includes so get_users_batch avoids a round-trip.
    Returns list of tweet dicts.
    """
    # Wrap in quotes for phrase matching and to prevent words like "and"/"or"
    # from being interpreted as boolean operators by the X API.
    # Truncate to 200 chars so the full query stays well under the 512-char limit.
    phrase = query[:200].replace('"', "'")
    params = {
        "query":        f'"{phrase}" -is:retweet lang:en',
        "max_results":  max(10, min(max_results, 100)),
        "tweet.fields": "created_at,author_id,lang",
        "expansions":   "author_id",
        "user.fields":  "created_at,public_metrics,profile_image_url,description,verified",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_BASE_URL}/tweets/search/recent",
            headers=_headers(),
            params=params,
        )

    _raise_for_status(response)
    body = response.json()

    # Cache users so get_users_batch can serve them without an extra call
    for u in body.get("includes", {}).get("users", []):
        parsed = _parse_user(u)
        _user_cache[parsed["id"]] = parsed

    return [_parse_tweet(t) for t in body.get("data", [])]


async def get_users_batch(user_ids: list[str]) -> list[dict]:
    """
    GET /2/users

    Cache-first: returns cached profiles for any ids already seen.
    Fetches the remainder in a single request (API limit: 100 ids).
    Returns list of account dicts.
    """
    results: list[dict] = []
    uncached: list[str] = []

    for uid in user_ids:
        if uid in _user_cache:
            results.append(_user_cache[uid])
        else:
            uncached.append(uid)

    if not uncached:
        return results

    # X API allows up to 100 ids per request
    for i in range(0, len(uncached), 100):
        batch = uncached[i : i + 100]
        params = {
            "ids":         ",".join(batch),
            "user.fields": "created_at,public_metrics,profile_image_url,description,verified",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{_BASE_URL}/users",
                headers=_headers(),
                params=params,
            )

        _raise_for_status(response)
        body = response.json()

        for u in body.get("data", []):
            parsed = _parse_user(u)
            _user_cache[parsed["id"]] = parsed
            results.append(parsed)

    return results


async def get_tweet_by_id(tweet_id: str) -> dict | None:
    """
    GET /2/tweets/:id

    Returns a single tweet dict in the same shape as search_recent,
    or None if the tweet is not found.
    """
    params = {"tweet.fields": "created_at,author_id,lang"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_BASE_URL}/tweets/{tweet_id}",
            headers=_headers(),
            params=params,
        )

    if response.status_code == 404:
        return None
    _raise_for_status(response)
    body = response.json()
    data = body.get("data")
    if not data:
        return None
    return _parse_tweet(data)


async def search_replies(tweet_id: str, max_results: int = 100) -> list[dict]:
    """
    GET /2/tweets/search/recent — replies to a specific tweet.

    Uses the structured filter `in_reply_to_tweet_id:{tweet_id}` so no phrase
    quoting is needed.  No lang filter — astroturf can come from any locale.
    Caches user objects from includes identical to search_recent.
    """
    params = {
        "query":        f"in_reply_to_tweet_id:{tweet_id} -is:retweet",
        "max_results":  max(10, min(max_results, 100)),
        "tweet.fields": "created_at,author_id,lang,in_reply_to_user_id",
        "expansions":   "author_id",
        "user.fields":  "created_at,public_metrics,profile_image_url,description,verified",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_BASE_URL}/tweets/search/recent",
            headers=_headers(),
            params=params,
        )

    _raise_for_status(response)
    body = response.json()

    for u in body.get("includes", {}).get("users", []):
        parsed = _parse_user(u)
        _user_cache[parsed["id"]] = parsed

    return [_parse_tweet(t) for t in body.get("data", [])]


async def get_users_by_usernames(usernames: list[str]) -> list[dict]:
    """
    GET /2/users/by?usernames=...

    Resolves @handles (with or without leading @) to full user profiles.
    Caches results in _user_cache.  Accepts up to 100 usernames per call.
    Returns list of account dicts in the same shape as get_users_batch.
    """
    cleaned = [u.lstrip("@") for u in usernames if u.strip()]
    if not cleaned:
        return []

    results: list[dict] = []
    for i in range(0, len(cleaned), 100):
        batch = cleaned[i : i + 100]
        params = {
            "usernames":   ",".join(batch),
            "user.fields": "created_at,public_metrics,profile_image_url,description,verified",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{_BASE_URL}/users/by",
                headers=_headers(),
                params=params,
            )

        _raise_for_status(response)
        body = response.json()

        for u in body.get("data", []):
            parsed = _parse_user(u)
            _user_cache[parsed["id"]] = parsed
            results.append(parsed)

    return results


async def get_user_tweets(user_id: str, start_time: int | None = None) -> list[dict]:
    """
    GET /2/users/{user_id}/tweets

    Returns up to 100 tweets for the user.
    start_time is a Unix int; converted to ISO-8601 before sending.
    """
    params: dict = {
        "max_results":  100,
        "tweet.fields": "created_at,lang,in_reply_to_user_id",
    }

    if start_time is not None:
        params["start_time"] = (
            datetime.fromtimestamp(start_time, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_BASE_URL}/users/{user_id}/tweets",
            headers=_headers(),
            params=params,
        )

    _raise_for_status(response)
    body = response.json()

    return [_parse_tweet(t, author_id=user_id) for t in body.get("data", [])]
