"""
Investigation pipeline orchestrator.

States: PENDING → SEARCHING → PROFILING → EXPANDING → ANALYZING → COMPLETE
Side states: FAILED, PARTIAL
"""

import asyncio
import hashlib
import re
import time
from typing import Callable, Awaitable

from backend.db import queries
from backend.services import call_manager, x_client, search_backend
from backend.core import matcher, scorer, analyzer, cluster

# Emit signature: async (stage: str, message: str) -> None
EmitFn = Callable[[str, str], Awaitable[None]]

def _tweet_text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.md5(normalized.encode()).hexdigest()


_TWEET_ID_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:twitter|x)\.com/\w+/status/(\d+)"
)

def extract_tweet_id(text: str) -> str | None:
    """Return the tweet ID from an x.com or twitter.com status URL, or None."""
    m = _TWEET_ID_RE.search(text)
    return m.group(1) if m else None


def clean_seed_text(text: str) -> str:
    """Strip URLs, @mentions, and hashtags; collapse whitespace."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#\w+", "", text)
    return re.sub(r"\s+", " ", text).strip()


DEPTH_CONFIG = {
    "QUICK":    {"max_expansions": 5,   "max_api_calls": 5},
    "STANDARD": {"max_expansions": 10,  "max_api_calls": 30},
    "DEEP":     {"max_expansions": 20,  "max_api_calls": 100},
}


async def run_investigation(
    db_path: str,
    investigation_id: int,
    seed_text: str,
    depth: str,
    emit: EmitFn,
) -> None:
    """
    Run the full pipeline for investigation_id.
    Calls emit(stage, message) at each stage transition.
    Updates the DB row throughout.
    """
    config = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["STANDARD"])

    try:
        # ── SEARCHING ────────────────────────────────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="SEARCHING", current_stage="SEARCHING",
        )
        await emit("SEARCHING", "Searching for matching tweets…")

        # If seed_text is a tweet URL, resolve it to tweet text first.
        original_input = seed_text
        tweet_id = extract_tweet_id(seed_text)
        if tweet_id:
            resolved = await call_manager.execute(
                db_path, "get_tweet_by_id",
                lambda: x_client.get_tweet_by_id(tweet_id),
                investigation_id,
            )
            if resolved:
                seed_text = resolved.get("text", seed_text)
                await queries.update_investigation(
                    db_path, investigation_id, seed_tweet_id=tweet_id
                )

        # Strip URLs, mentions, hashtags before using as search query / matcher.
        query_text = clean_seed_text(seed_text)

        # Use only the first 6 words as the X API search phrase so semantic
        # rewrites (same opening, different phrasing) are still returned.
        # The full query_text is used locally by find_matches for accurate scoring.
        _words = query_text.split()
        search_phrase = " ".join(_words[:min(6, len(_words))])

        search_result = await search_backend.search(search_phrase, limit=100)
        raw_tweets = search_result["tweets"]
        _source = search_result["source"]

        if _source == "SCRAPER":
            # Persist user profiles returned by the scraper
            for user in search_result.get("users", []):
                await queries.upsert_account(db_path, user)
        else:
            # API path — log the call for budget tracking
            await call_manager.log_call(db_path, "search_recent", investigation_id)

        # Record which backend served this search
        await queries.update_investigation(
            db_path, investigation_id, search_source=_source
        )

        matched = matcher.find_matches(query_text, raw_tweets)

        # Persist stub accounts + tweets
        for tweet in raw_tweets:
            acct_id = tweet.get("author_id") or tweet.get("account_id")
            await queries.upsert_account(db_path, {"id": acct_id, "handle": tweet.get("author_handle", acct_id)})
            tweet_row = {**tweet, "account_id": acct_id, "text_hash": _tweet_text_hash(tweet.get("text", ""))}
            await queries.upsert_tweet(db_path, tweet_row)

        for match in matched:
            acct_id = match.get("author_id") or match.get("account_id")
            await queries.add_tweet_match(
                db_path, investigation_id,
                match["id"], match["similarity"], match["match_type"],
            )

        unique_accounts = list({(t.get("author_id") or t.get("account_id")) for t in matched})
        await emit("SEARCHING", f"Found {len(matched)} matching tweets from {len(unique_accounts)} accounts")

        if not matched:
            await queries.update_investigation(
                db_path, investigation_id,
                status="FAILED", failed_at_stage="SEARCHING",
                failure_reason="No matching tweets found",
            )
            await emit("FAILED", "No matching tweets found")
            return

        # Pin the seed tweet to the earliest matched tweet
        earliest_match = min(
            (m for m in matched if m.get("posted_at") is not None),
            key=lambda m: m["posted_at"],
            default=None,
        )
        if earliest_match:
            await queries.update_investigation(
                db_path, investigation_id, seed_tweet_id=earliest_match["id"]
            )

        # ── PROFILING ─────────────────────────────────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="PROFILING", current_stage="PROFILING",
        )
        await emit("PROFILING", f"Fetching profiles for {len(unique_accounts)} accounts…")

        profiles_raw = await call_manager.execute(
            db_path, "get_users_batch",
            lambda: x_client.get_users_batch(unique_accounts),
            investigation_id,
        )

        scored_profiles: list[dict] = []
        for profile in profiles_raw:
            bot_score = scorer.compute_bot_score(profile)
            profile = {**profile, "bot_score": bot_score, "profile_fetched": True}
            await queries.upsert_account(db_path, profile)
            scored_profiles.append(profile)

        # Every account that posted matching text is a suspect — bot score
        # affects role assignment and confidence, not whether to proceed.
        suspects = scored_profiles
        high_bot = sum(1 for p in suspects if p["bot_score"] >= 0.4)
        await emit("PROFILING", f"Scored {len(suspects)} accounts ({high_bot} high bot-score)")

        if not suspects:
            await queries.update_investigation(
                db_path, investigation_id,
                status="FAILED", failed_at_stage="PROFILING",
                failure_reason="No accounts found for matched tweets",
            )
            await emit("FAILED", "No accounts found for matched tweets")
            return

        # ── EXPANDING ─────────────────────────────────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="EXPANDING", current_stage="EXPANDING",
        )

        top_suspects = sorted(suspects, key=lambda p: p["bot_score"], reverse=True)[
            : config["max_expansions"]
        ]
        all_historical: list[dict] = []
        fetch_success = 0

        for i, suspect in enumerate(top_suspects):
            await emit("EXPANDING", f"Fetching histories {i + 1}/{len(top_suspects)}")
            try:
                # Cache-first: skip if tweets recently fetched
                existing = await queries.get_account(db_path, suspect["id"])
                if existing and not call_manager.is_tweet_history_stale(existing.get("tweets_fetched_at")):
                    await call_manager.log_call(db_path, "get_user_tweets", investigation_id, cache_hit=True)
                    fetch_success += 1
                    continue

                history = await call_manager.execute(
                    db_path, "get_user_tweets",
                    lambda uid=suspect["id"]: x_client.get_user_tweets(uid),
                    investigation_id,
                )
                for tweet in history:
                    tweet_row = {**tweet, "account_id": suspect["id"], "text_hash": _tweet_text_hash(tweet.get("text", ""))}
                    await queries.upsert_tweet(db_path, tweet_row)
                all_historical.extend(history)
                fetch_success += 1
            except Exception:
                continue  # partial failure is acceptable

        if fetch_success == 0:
            await queries.update_investigation(
                db_path, investigation_id,
                status="FAILED", failed_at_stage="EXPANDING",
                failure_reason="All expansion fetches failed",
            )
            await emit("FAILED", "All expansion fetches failed")
            return

        if fetch_success < len(top_suspects):
            await emit(
                "PARTIAL",
                f"{fetch_success}/{len(top_suspects)} accounts fetched, proceeding to analysis",
            )

        # Cell members
        origin_account_id = analyzer.detect_origin(top_suspects, matched)
        for suspect in top_suspects:
            if suspect["id"] == origin_account_id:
                role = "ORIGIN"
            elif suspect["bot_score"] >= 0.6:
                role = "AMPLIFIER"
            else:
                role = "SUSPECTED"
            match_count = sum(1 for m in matched if (m.get("author_id") or m.get("account_id")) == suspect["id"])
            await queries.add_cell_member(
                db_path, investigation_id, suspect["id"], role, match_count,
            )

        # ── ANALYZING ────────────────────────────────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="ANALYZING", current_stage="ANALYZING",
        )
        await emit("ANALYZING", "Computing burst window and origin…")

        api_calls_used = await queries.count_calls_for_investigation(db_path, investigation_id)

        all_tweets_for_analysis = matched + all_historical
        burst_info = analyzer.detect_burst_window(all_tweets_for_analysis)
        bot_scores = [p["bot_score"] for p in top_suspects]
        pattern = analyzer.classify_pattern(
            len(top_suspects), burst_info["burst_window_s"], bot_scores,
        )
        confidence = analyzer.compute_confidence(
            len(top_suspects), burst_info["burst_window_s"], bot_scores, len(matched),
        )
        verdict = (
            "COORDINATED" if confidence > 0.6
            else "UNCERTAIN" if confidence > 0.3
            else "ORGANIC"
        )

        await queries.update_investigation(
            db_path, investigation_id,
            status="COMPLETE",
            current_stage="COMPLETE",
            verdict=verdict,
            confidence=confidence,
            pattern_type=pattern,
            cell_size=len(top_suspects),
            burst_window_s=burst_info["burst_window_s"],
            origin_account=origin_account_id,
            depth_used=depth,
            api_calls_used=api_calls_used,
            ran_at=int(time.time()), last_accessed_at=int(time.time()),
        )
        await emit("COMPLETE", str(investigation_id))

    except call_manager.RateLimitError as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", f"Rate limit hit: {exc}")

    except call_manager.BudgetExceededError as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", f"Budget exceeded: {exc}")

    except Exception as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", str(exc))


def _strip_leading_mention(text: str) -> str:
    """Strip the leading @handle from a reply tweet.

    X prepends the replied-to handle to every reply body — e.g.
    "@kareemformayor Libraries are full of…".  That mention is structural
    noise: it's identical across every reply to the same tweet and will
    collapse the entire reply thread into one false cluster if left in.
    """
    return re.sub(r"^(@\w+\s*)+", "", text).strip()


def _reply_ratio(tweets: list[dict]) -> float:
    """Fraction of tweets that are replies. Returns 0.0 if no tweets."""
    if not tweets:
        return 0.0
    return sum(1 for t in tweets if t.get("is_reply")) / len(tweets)


async def run_reply_investigation(
    db_path: str,
    investigation_id: int,
    tweet_url: str,
    depth: str,
    emit: EmitFn,
) -> None:
    """
    Reply-graph pipeline: fetch all replies to a tweet, score every replier,
    cluster replies thematically, and surface infrastructure accounts.

    Primary signal: bot_score + reply_ratio (account shape).
    Secondary signal: thematic clusters across replies.

    States: PENDING → SEARCHING → PROFILING → EXPANDING → ANALYZING → COMPLETE
    """
    config = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["STANDARD"])

    try:
        # ── SEARCHING: resolve URL → tweet ID → fetch replies ─────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="SEARCHING", current_stage="SEARCHING",
        )
        await emit("SEARCHING", "Resolving tweet URL…")

        tweet_id = extract_tweet_id(tweet_url)
        if not tweet_id:
            await queries.update_investigation(
                db_path, investigation_id,
                status="FAILED", failed_at_stage="SEARCHING",
                failure_reason="Could not extract tweet ID from URL",
            )
            await emit("FAILED", "Could not extract tweet ID from URL")
            return

        # Persist the seed tweet if we can resolve it
        seed_tweet = await call_manager.execute(
            db_path, "get_tweet_by_id",
            lambda: x_client.get_tweet_by_id(tweet_id),
            investigation_id,
        )
        if seed_tweet:
            await queries.update_investigation(
                db_path, investigation_id, seed_tweet_id=tweet_id
            )

        await emit("SEARCHING", f"Fetching replies to tweet {tweet_id}…")

        raw_replies = await call_manager.execute(
            db_path, "search_replies",
            lambda: x_client.search_replies(tweet_id, max_results=100),
            investigation_id,
        )

        if not raw_replies:
            await queries.update_investigation(
                db_path, investigation_id,
                status="FAILED", failed_at_stage="SEARCHING",
                failure_reason="No replies found (tweet may be too old or have no replies)",
            )
            await emit("FAILED", "No replies found")
            return

        # Persist reply accounts (stubs) and tweets
        for tweet in raw_replies:
            acct_id = tweet.get("author_id")
            await queries.upsert_account(db_path, {"id": acct_id, "handle": acct_id})
            tweet_row = {**tweet, "account_id": acct_id, "text_hash": _tweet_text_hash(tweet.get("text", ""))}
            await queries.upsert_tweet(db_path, tweet_row)

        unique_replier_ids = list({t.get("author_id") for t in raw_replies})
        await emit("SEARCHING", f"Found {len(raw_replies)} replies from {len(unique_replier_ids)} accounts")

        # ── PROFILING: score every replier ────────────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="PROFILING", current_stage="PROFILING",
        )
        await emit("PROFILING", f"Scoring {len(unique_replier_ids)} repliers…")

        profiles_raw = await call_manager.execute(
            db_path, "get_users_batch",
            lambda: x_client.get_users_batch(unique_replier_ids),
            investigation_id,
        )

        scored_profiles: list[dict] = []
        for profile in profiles_raw:
            bot_score = scorer.compute_bot_score(profile)
            profile = {**profile, "bot_score": bot_score, "profile_fetched": True}
            await queries.upsert_account(db_path, profile)
            scored_profiles.append(profile)

        high_bot = sum(1 for p in scored_profiles if p["bot_score"] >= 0.4)
        await emit("PROFILING", f"Scored {len(scored_profiles)} accounts ({high_bot} high bot-score)")

        # ── EXPANDING: fetch timelines for top suspects → reply ratio ─────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="EXPANDING", current_stage="EXPANDING",
        )

        # Sort by bot_score descending; reply-ratio analysis is most valuable
        # for the accounts that already look suspicious
        top_suspects = sorted(scored_profiles, key=lambda p: p["bot_score"], reverse=True)[
            : config["max_expansions"]
        ]

        all_historical: list[dict] = []
        account_reply_ratios: dict[str, float] = {}
        fetch_success = 0

        for i, suspect in enumerate(top_suspects):
            await emit("EXPANDING", f"Fetching timeline {i + 1}/{len(top_suspects)}: @{suspect['handle']}")
            try:
                existing = await queries.get_account(db_path, suspect["id"])
                if existing and not call_manager.is_tweet_history_stale(existing.get("tweets_fetched_at")):
                    await call_manager.log_call(db_path, "get_user_tweets", investigation_id, cache_hit=True)
                    cached = await queries.get_tweets_by_account_ids(db_path, [suspect["id"]])
                    account_reply_ratios[suspect["id"]] = _reply_ratio(cached)
                    all_historical.extend(cached)
                    fetch_success += 1
                    continue

                history = await call_manager.execute(
                    db_path, "get_user_tweets",
                    lambda uid=suspect["id"]: x_client.get_user_tweets(uid),
                    investigation_id,
                )
                for tweet in history:
                    tweet_row = {
                        **tweet,
                        "account_id": suspect["id"],
                        "text_hash": _tweet_text_hash(tweet.get("text", "")),
                    }
                    await queries.upsert_tweet(db_path, tweet_row)
                await queries.upsert_account(db_path, {**suspect, "tweets_fetched": True})

                account_reply_ratios[suspect["id"]] = _reply_ratio(history)
                all_historical.extend({**t, "author_id": suspect["id"]} for t in history)
                fetch_success += 1

            except Exception:
                continue

        if fetch_success < len(top_suspects):
            await emit(
                "PARTIAL",
                f"{fetch_success}/{len(top_suspects)} timelines fetched, proceeding",
            )

        # ── ANALYZING ─────────────────────────────────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="ANALYZING", current_stage="ANALYZING",
        )
        await emit("ANALYZING", "Clustering replies and computing account shapes…")

        # Strip the leading @mention before clustering — it's structural noise
        # identical across every reply to the same tweet and would otherwise
        # collapse the entire thread into one false NEAR-EXACT cluster.
        replies_for_clustering = [
            {**t, "text": _strip_leading_mention(t.get("text", ""))}
            for t in raw_replies
        ]

        # Thematic clustering across all replies
        result = cluster.build_clusters(replies_for_clustering, min_cluster_size=1)
        clusters_found = result["clusters"]

        for c in clusters_found:
            for member in c["members"]:
                await queries.add_tweet_match(
                    db_path, investigation_id,
                    member["tweet_id"], c["similarity"], c["match_type"],
                )

        # Cell membership: bot_score ≥ 0.4 OR reply_ratio ≥ 0.8
        # Bot_score is the primary gate — reply_ratio upgrades role to AMPLIFIER
        suspicious = [
            p for p in scored_profiles
            if p["bot_score"] >= 0.4
            or account_reply_ratios.get(p["id"], 0.0) >= 0.8
        ]

        origin_account_id = analyzer.detect_origin(suspicious, raw_replies)

        for profile in suspicious:
            pid = profile["id"]
            ratio = account_reply_ratios.get(pid, 0.0)
            if pid == origin_account_id:
                role = "ORIGIN"
            elif profile["bot_score"] >= 0.6 or ratio >= 0.9:
                role = "AMPLIFIER"
            else:
                role = "SUSPECTED"
            match_count = sum(1 for t in raw_replies if t.get("author_id") == pid)
            await queries.add_cell_member(db_path, investigation_id, pid, role, match_count)

        # Confidence weighted toward bot_score distribution since text
        # similarity is weaker signal here than account shape
        bot_scores = [p["bot_score"] for p in suspicious]
        burst_info = analyzer.detect_burst_window(raw_replies)
        pattern = analyzer.classify_pattern(len(suspicious), burst_info["burst_window_s"], bot_scores)

        # Confidence: use match_count = number of thematic clusters as proxy
        confidence = analyzer.compute_confidence(
            len(suspicious), burst_info["burst_window_s"], bot_scores, len(clusters_found)
        )
        verdict = (
            "COORDINATED" if confidence > 0.6
            else "UNCERTAIN" if confidence > 0.3
            else "ORGANIC"
        )

        api_calls_used = await queries.count_calls_for_investigation(db_path, investigation_id)
        await queries.update_investigation(
            db_path, investigation_id,
            status="COMPLETE", current_stage="COMPLETE",
            verdict=verdict, confidence=confidence, pattern_type=pattern,
            cell_size=len(suspicious), burst_window_s=burst_info["burst_window_s"],
            origin_account=origin_account_id, depth_used=depth,
            api_calls_used=api_calls_used, ran_at=int(time.time()), last_accessed_at=int(time.time()),
        )
        await emit("COMPLETE", str(investigation_id))

    except call_manager.RateLimitError as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", f"Rate limit hit: {exc}")

    except call_manager.BudgetExceededError as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", f"Budget exceeded: {exc}")

    except Exception as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", str(exc))


def _parse_handles(handles_text: str) -> list[str]:
    """Split a free-form string of @handles into a clean list (no @, no dupes)."""
    raw = re.split(r"[\s,]+", handles_text.strip())
    seen: set[str] = set()
    result: list[str] = []
    for h in raw:
        h = h.lstrip("@").strip()
        if h and h not in seen:
            seen.add(h)
            result.append(h)
    return result


async def run_profile_investigation(
    db_path: str,
    investigation_id: int,
    handles_text: str,
    depth: str,
    emit: EmitFn,
    min_cluster_size: int = 2,
) -> None:
    """
    Profile-mode pipeline: given a list of @handles, fetch their recent tweets,
    cluster for coordination, and produce a report using the same DB schema.

    States: PENDING → SEARCHING → PROFILING → EXPANDING → ANALYZING → COMPLETE
    """
    config = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["STANDARD"])
    handles = _parse_handles(handles_text)

    try:
        # ── SEARCHING: resolve handles → profiles ─────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="SEARCHING", current_stage="SEARCHING",
        )
        await emit("SEARCHING", f"Resolving {len(handles)} handles…")

        profiles_raw = await call_manager.execute(
            db_path, "get_users_by_usernames",
            lambda: x_client.get_users_by_usernames(handles),
            investigation_id,
        )

        if not profiles_raw:
            await queries.update_investigation(
                db_path, investigation_id,
                status="FAILED", failed_at_stage="SEARCHING",
                failure_reason="No accounts found for given handles",
            )
            await emit("FAILED", "No accounts found for given handles")
            return

        await emit("SEARCHING", f"Resolved {len(profiles_raw)}/{len(handles)} handles")

        # ── PROFILING: score accounts ─────────────────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="PROFILING", current_stage="PROFILING",
        )
        await emit("PROFILING", f"Scoring {len(profiles_raw)} accounts…")

        scored_profiles: list[dict] = []
        for profile in profiles_raw:
            bot_score = scorer.compute_bot_score(profile)
            profile = {**profile, "bot_score": bot_score, "profile_fetched": True}
            await queries.upsert_account(db_path, profile)
            scored_profiles.append(profile)

        high_bot = sum(1 for p in scored_profiles if p["bot_score"] >= 0.4)
        await emit("PROFILING", f"Scored {len(scored_profiles)} accounts ({high_bot} high bot-score)")

        # ── EXPANDING: fetch tweet histories ──────────────────────────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="EXPANDING", current_stage="EXPANDING",
        )

        profiles_to_fetch = scored_profiles[: config["max_expansions"]]
        all_tweets: list[dict] = []
        fetch_success = 0

        for i, profile in enumerate(profiles_to_fetch):
            await emit("EXPANDING", f"Fetching tweets {i + 1}/{len(profiles_to_fetch)}: @{profile['handle']}")
            try:
                existing = await queries.get_account(db_path, profile["id"])
                if existing and not call_manager.is_tweet_history_stale(existing.get("tweets_fetched_at")):
                    # Cache hit: load from DB instead of API
                    await call_manager.log_call(db_path, "get_user_tweets", investigation_id, cache_hit=True)
                    cached = await queries.get_tweets_by_account_ids(db_path, [profile["id"]])
                    all_tweets.extend(cached)
                    fetch_success += 1
                    continue

                history = await call_manager.execute(
                    db_path, "get_user_tweets",
                    lambda uid=profile["id"]: x_client.get_user_tweets(uid),
                    investigation_id,
                )
                for tweet in history:
                    tweet_row = {
                        **tweet,
                        "account_id": profile["id"],
                        "text_hash": _tweet_text_hash(tweet.get("text", "")),
                    }
                    await queries.upsert_tweet(db_path, tweet_row)
                # Mark tweets as freshly fetched on the account row
                await queries.upsert_account(db_path, {**profile, "tweets_fetched": True})
                all_tweets.extend({**t, "author_id": profile["id"]} for t in history)
                fetch_success += 1

            except Exception:
                continue

        if fetch_success == 0:
            await queries.update_investigation(
                db_path, investigation_id,
                status="FAILED", failed_at_stage="EXPANDING",
                failure_reason="All timeline fetches failed",
            )
            await emit("FAILED", "All timeline fetches failed")
            return

        if fetch_success < len(profiles_to_fetch):
            await emit(
                "PARTIAL",
                f"{fetch_success}/{len(profiles_to_fetch)} timelines fetched, proceeding",
            )

        await emit("EXPANDING", f"Collected {len(all_tweets)} tweets across {fetch_success} accounts")

        # ── ANALYZING: cluster → cell members → burst → verdict ──────────────
        await queries.update_investigation(
            db_path, investigation_id,
            status="ANALYZING", current_stage="ANALYZING",
        )
        await emit("ANALYZING", f"Clustering {len(all_tweets)} tweets…")

        # Strip leading @mentions — profile timelines include replies where X
        # prepends the replied-to handle.  Without stripping, that shared token
        # collapses unrelated tweets into false high-similarity clusters, exactly
        # the same bug that was fixed in reply mode.
        tweets_for_clustering = [
            {**t, "text": _strip_leading_mention(t.get("text", ""))}
            for t in all_tweets
        ]

        result = cluster.build_clusters(tweets_for_clustering, min_cluster_size=min_cluster_size)
        clusters_found = result["clusters"]
        self_repetitions = result["self_repetitions"]

        await emit("ANALYZING", f"Found {len(clusters_found)} coordination cluster(s)")

        # Persist tweet matches from all clusters
        for c in clusters_found:
            for member in c["members"]:
                await queries.add_tweet_match(
                    db_path, investigation_id,
                    member["tweet_id"], c["similarity"], c["match_type"],
                )

        # Tally per-account cluster participation
        account_cluster_counts: dict[str, int] = {}
        for c in clusters_found:
            for member in c["members"]:
                aid = member["author_id"]
                account_cluster_counts[aid] = account_cluster_counts.get(aid, 0) + 1

        if not clusters_found:
            api_calls_used = await queries.count_calls_for_investigation(db_path, investigation_id)
            await queries.update_investigation(
                db_path, investigation_id,
                status="COMPLETE", current_stage="COMPLETE",
                verdict="ORGANIC", confidence=0.0, pattern_type="INCONCLUSIVE",
                cell_size=0, burst_window_s=0, origin_account=None,
                depth_used=depth, api_calls_used=api_calls_used,
                ran_at=int(time.time()), last_accessed_at=int(time.time()),
            )
            await emit("COMPLETE", str(investigation_id))
            return

        # Origin: author of the earliest tweet in the largest cluster
        largest_cluster = max(clusters_found, key=lambda c: len(c["members"]))
        earliest_member = min(
            (m for m in largest_cluster["members"] if m.get("posted_at") is not None),
            key=lambda m: m["posted_at"],
            default=None,
        )
        origin_account_id = earliest_member["author_id"] if earliest_member else None
        if earliest_member:
            await queries.update_investigation(
                db_path, investigation_id, seed_tweet_id=earliest_member["tweet_id"]
            )

        # Add cell members (only accounts in coordination clusters)
        cell_profiles = [p for p in scored_profiles if p["id"] in account_cluster_counts]
        for profile in cell_profiles:
            pid = profile["id"]
            if pid == origin_account_id:
                role = "ORIGIN"
            elif profile["bot_score"] >= 0.6:
                role = "AMPLIFIER"
            else:
                role = "SUSPECTED"
            await queries.add_cell_member(
                db_path, investigation_id, pid, role, account_cluster_counts[pid]
            )

        # Burst detection across all matched tweet timestamps
        matched_timestamps = [
            {"posted_at": m["posted_at"]}
            for c in clusters_found
            for m in c["members"]
            if m.get("posted_at") is not None
        ]
        burst_info = analyzer.detect_burst_window(matched_timestamps)
        bot_scores = [p["bot_score"] for p in cell_profiles]
        pattern = analyzer.classify_pattern(len(cell_profiles), burst_info["burst_window_s"], bot_scores)
        confidence = analyzer.compute_confidence(
            len(cell_profiles), burst_info["burst_window_s"], bot_scores, len(clusters_found)
        )
        verdict = (
            "COORDINATED" if confidence > 0.6
            else "UNCERTAIN" if confidence > 0.3
            else "ORGANIC"
        )

        api_calls_used = await queries.count_calls_for_investigation(db_path, investigation_id)
        await queries.update_investigation(
            db_path, investigation_id,
            status="COMPLETE", current_stage="COMPLETE",
            verdict=verdict, confidence=confidence, pattern_type=pattern,
            cell_size=len(cell_profiles), burst_window_s=burst_info["burst_window_s"],
            origin_account=origin_account_id, depth_used=depth,
            api_calls_used=api_calls_used, ran_at=int(time.time()), last_accessed_at=int(time.time()),
        )
        await emit("COMPLETE", str(investigation_id))

    except call_manager.RateLimitError as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", f"Rate limit hit: {exc}")

    except call_manager.BudgetExceededError as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", f"Budget exceeded: {exc}")

    except Exception as exc:
        await queries.update_investigation(
            db_path, investigation_id,
            status="FAILED", failure_reason=str(exc),
        )
        await emit("FAILED", str(exc))
