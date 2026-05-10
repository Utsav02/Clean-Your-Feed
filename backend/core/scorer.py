"""
Bot score heuristics.

compute_bot_score  — stored on account row (0.0–1.0)
compute_combined_score — derived at read time, never stored
"""

import re
import time


def has_numeric_suffix(handle: str) -> bool:
    """Return True if the handle ends with 4+ consecutive digits.

    Real people rarely name themselves @Name12345678.  Platforms auto-append
    digits when a chosen username is taken, so a long numeric suffix is a
    reliable signal for auto-generated or throwaway accounts.
    """
    return bool(re.search(r"\d{4,}$", handle))


def compute_bot_score(account: dict) -> float:
    """
    Heuristic bot score based on account metadata.

    Rules:
        account age < 90 days          → +0.30
        account age < 365 days         → +0.10   (exclusive with <90 check)
        following/followers ratio > 10 → +0.30
        following/followers ratio > 3  → +0.10   (exclusive with >10 check)
        default_profile_img == 1       → +0.20
        no description                 → +0.10
        tweet_rate > 50 tweets/day     → +0.20
        tweet_rate > 20 tweets/day     → +0.10   (exclusive with >50 check)
        handle ends with ≥4 digits     → +0.15

    Capped at 1.0.
    """
    score = 0.0
    now = time.time()

    age_days: float = 0.0
    created_at = account.get("created_at")
    if created_at is not None:
        age_days = (now - created_at) / 86400
        if age_days < 90:
            score += 0.30
        elif age_days < 365:
            score += 0.10

    tweet_count = account.get("tweet_count") or 0
    if age_days > 0 and tweet_count > 0:
        daily_rate = tweet_count / age_days
        if daily_rate > 50:
            score += 0.20
        elif daily_rate > 20:
            score += 0.10

    followers = account.get("followers") or 0
    following = account.get("following") or 0
    if followers > 0:
        ratio = following / followers
        if ratio > 10:
            score += 0.30
        elif ratio > 3:
            score += 0.10
    elif following > 0:
        # Has following but zero followers — treat as worst case
        score += 0.30

    if account.get("default_profile_img"):
        score += 0.20

    description = account.get("description")
    if not description:
        score += 0.10

    if has_numeric_suffix(account.get("handle", "")):
        score += 0.15

    return min(score, 1.0)


def compute_combined_score(bot_score: float, investigation_count: int) -> float:
    """
    Combined score computed at read time.

        base       = bot_score
        freq_bonus = min(investigation_count * 0.05, 0.20)
        combined   = min(base + freq_bonus, 1.0)
    """
    freq_bonus = min(investigation_count * 0.05, 0.20)
    return min(bot_score + freq_bonus, 1.0)
