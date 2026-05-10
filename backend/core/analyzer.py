"""
Burst window detection, origin identification, pattern classification,
and confidence scoring.  Pure local computation — no DB or API calls.
"""

import re
import statistics
from collections import defaultdict


_LEADING_MENTION_RE = re.compile(r"^(@\w+\s*)+")
_MENTION_RE = re.compile(r"@(\w+)")


def _parse_targets(text: str) -> list[str]:
    """Extract @handles that appear at the start of a reply (the reply-to targets)."""
    m = _LEADING_MENTION_RE.match(text)
    if not m:
        return []
    return [h.lower() for h in _MENTION_RE.findall(m.group(0))]


def _strip_leading_mention(text: str) -> str:
    return _LEADING_MENTION_RE.sub("", text).strip()


def analyze_timing(
    cell_members: list[dict],
    reply_tweets: list[dict],
    seed_posted_at: int | None,
) -> dict:
    """
    Timing-based coordination signals. All data from DB — no API calls.

    cell_members: rows from get_investigation_report cell_members
    reply_tweets: tweet_matches rows (for reply investigations, these are the replies)
    seed_posted_at: Unix timestamp of the seed tweet, if known

    Returns:
        reply_speed: per-account seconds between seed tweet and their reply
            [{account_id, handle, delay_s}] sorted by delay_s
        speed_cluster: accounts that replied within the same 5-minute window
            [{window_start, window_end, handles}]
        creation_clusters: groups of accounts created within 30 days of each other
            [{window_label, accounts: [{handle, created_at}]}]
        inter_reply_regularity: per-account coefficient of variation of gaps between
            their own replies — low CV (< 0.3) suggests scheduled/automated posting
            [{handle, cv, n_gaps, mean_gap_s}]
    """
    handle_map = {m["account_id"]: m.get("handle", m["account_id"]) for m in cell_members}
    created_map = {m["account_id"]: m.get("created_at") for m in cell_members}

    # ── Reply speed to seed ───────────────────────────────────────────────
    reply_speed: list[dict] = []
    if seed_posted_at:
        # Build earliest reply per account from tweet_matches
        earliest: dict[str, int] = {}
        for t in reply_tweets:
            aid = t.get("account_id") or t.get("author_id")
            ts = t.get("posted_at")
            if aid and ts and ts >= seed_posted_at:
                if aid not in earliest or ts < earliest[aid]:
                    earliest[aid] = ts
        for aid, ts in earliest.items():
            reply_speed.append({
                "account_id": aid,
                "handle":     handle_map.get(aid, aid),
                "delay_s":    ts - seed_posted_at,
            })
        reply_speed.sort(key=lambda x: x["delay_s"])

    # ── Speed cluster: who replied within 5 min of each other ────────────
    speed_cluster: list[dict] = []
    if len(reply_speed) >= 2:
        WINDOW = 300  # 5 minutes
        speeds = sorted(reply_speed, key=lambda x: x["delay_s"])
        left = 0
        for right in range(len(speeds)):
            while speeds[right]["delay_s"] - speeds[left]["delay_s"] > WINDOW:
                left += 1
            count = right - left + 1
            if count >= 3:  # 3+ accounts replying within 5 min = notable
                cluster_handles = [s["handle"] for s in speeds[left:right + 1]]
                # Only keep the largest non-overlapping window
                if not speed_cluster or speed_cluster[-1]["handles"] != cluster_handles:
                    speed_cluster.append({
                        "window_start": speeds[left]["delay_s"],
                        "window_end":   speeds[right]["delay_s"],
                        "handles":      cluster_handles,
                    })

    # ── Account creation clustering (30-day windows) ──────────────────────
    creation_clusters: list[dict] = []
    dated = sorted(
        [(aid, ts) for aid, ts in created_map.items() if ts],
        key=lambda x: x[1],
    )
    if dated:
        WINDOW_DAYS = 30 * 86400
        left = 0
        for right in range(len(dated)):
            while dated[right][1] - dated[left][1] > WINDOW_DAYS:
                left += 1
            if right - left + 1 >= 2:
                group = dated[left:right + 1]
                # Avoid duplicates — only emit when the group changes
                handles_in_group = [handle_map.get(a, a) for a, _ in group]
                if not creation_clusters or creation_clusters[-1]["handles"] != handles_in_group:
                    import datetime as dt
                    label = dt.datetime.utcfromtimestamp(dated[left][1]).strftime("%b %Y")
                    creation_clusters.append({
                        "window_label": label,
                        "handles":      handles_in_group,
                        "account_count": len(group),
                    })
        # Keep only largest clusters
        creation_clusters.sort(key=lambda x: x["account_count"], reverse=True)
        creation_clusters = creation_clusters[:5]

    # ── Inter-reply regularity (CV of gaps between own posts) ─────────────
    # Uses reply_tweets which already has timestamps; sort per account
    by_account: dict[str, list[int]] = defaultdict(list)
    for t in reply_tweets:
        aid = t.get("account_id") or t.get("author_id")
        ts = t.get("posted_at")
        if aid and ts:
            by_account[aid].append(ts)

    inter_reply_regularity: list[dict] = []
    for aid, timestamps in by_account.items():
        if len(timestamps) < 3:
            continue
        timestamps_sorted = sorted(timestamps)
        gaps = [timestamps_sorted[i+1] - timestamps_sorted[i] for i in range(len(timestamps_sorted)-1)]
        if not gaps:
            continue
        mean_gap = statistics.mean(gaps)
        if mean_gap == 0:
            continue
        try:
            stdev = statistics.stdev(gaps)
        except statistics.StatisticsError:
            continue
        cv = stdev / mean_gap
        inter_reply_regularity.append({
            "account_id": aid,
            "handle":     handle_map.get(aid, aid),
            "cv":         round(cv, 3),
            "n_gaps":     len(gaps),
            "mean_gap_s": round(mean_gap),
        })
    # Sort by CV ascending — most regular (most bot-like) first
    inter_reply_regularity.sort(key=lambda x: x["cv"])

    return {
        "reply_speed":           reply_speed,
        "speed_cluster":         speed_cluster,
        "creation_clusters":     creation_clusters,
        "inter_reply_regularity": inter_reply_regularity,
    }


def cell_coordination_score(
    cell_members: list[dict],
    timing: dict,
    shared_targets: list[dict],
    theme_clusters: list[dict],
) -> dict:
    """
    Aggregate cell-level coordination score (0.0–1.0) separate from per-account bot_score.
    This answers "how coordinated is this cell as a whole" rather than "is this account a bot".

    Components (each 0–1, weighted):
        timing_score     0.30 — speed cluster + creation clustering
        network_score    0.25 — shared targets across cell
        content_score    0.25 — thematic clusters with 3+ accounts
        behavior_score   0.20 — avg reply_ratio + regularity signals
    """
    score = 0.0
    evidence: list[str] = []

    # Timing (0.30)
    timing_score = 0.0
    if timing.get("speed_cluster"):
        largest_speed = max(len(c["handles"]) for c in timing["speed_cluster"])
        timing_score += min(largest_speed / len(cell_members), 1.0) * 0.15
        evidence.append(f"{largest_speed} accounts replied within 5 min of each other")
    if timing.get("creation_clusters"):
        largest_creation = timing["creation_clusters"][0]["account_count"]
        timing_score += min(largest_creation / len(cell_members), 1.0) * 0.15
        evidence.append(f"{largest_creation} accounts created within 30 days of each other")
    score += timing_score

    # Network (0.25)
    meaningful_shared = [s for s in shared_targets if s.get("account_count", 0) >= 3]
    if meaningful_shared:
        network_score = min(len(meaningful_shared) / 5, 1.0) * 0.25
        score += network_score
        evidence.append(f"{len(meaningful_shared)} targets shared by 3+ accounts")

    # Content (0.25)
    multi_account_clusters = [c for c in theme_clusters if len(set(m["author_id"] for m in c["members"])) >= 3]
    if multi_account_clusters:
        content_score = min(len(multi_account_clusters) / 5, 1.0) * 0.25
        score += content_score
        evidence.append(f"{len(multi_account_clusters)} thematic clusters with 3+ accounts")

    # Behavior (0.20)
    high_reply_ratio = sum(1 for m in cell_members if (m.get("reply_ratio") or 0) >= 0.8)
    regular_posters  = sum(1 for r in timing.get("inter_reply_regularity", []) if r["cv"] < 0.3)
    behavior_score = min((high_reply_ratio + regular_posters) / max(len(cell_members), 1), 1.0) * 0.20
    score += behavior_score
    if high_reply_ratio:
        evidence.append(f"{high_reply_ratio} accounts with 80%+ reply ratio")
    if regular_posters:
        evidence.append(f"{regular_posters} accounts with suspiciously regular posting intervals")

    return {
        "score":    round(min(score, 1.0), 3),
        "evidence": evidence,
    }


def analyze_profiles(
    tweets: list[dict],
    top_n_targets: int = 5,
    min_cluster_words: int = 8,
) -> dict:
    """
    Pure computation on stored tweets for cell members.
    No API calls.

    tweets: rows from get_cell_member_tweets — each has account_id, handle, text, posted_at

    Returns:
        accounts: per-account summary
            handle, reply_ratio, top_targets [{handle, count}]
        shared_targets: targets replied to by ≥2 cell members
            [{target, count (distinct accounts), by [handles]}]
        theme_clusters: thematic clusters across historical replies
            from the cluster engine (same as reply investigation)
    """
    from backend.core import cluster as cluster_mod

    # Group by account
    by_account: dict[str, list[dict]] = defaultdict(list)
    handle_map: dict[str, str] = {}
    for t in tweets:
        by_account[t["account_id"]].append(t)
        handle_map[t["account_id"]] = t.get("handle", t["account_id"])

    accounts = []
    # target → set of account_ids that replied to it
    target_accounts: dict[str, set] = defaultdict(set)

    for account_id, acct_tweets in by_account.items():
        total = len(acct_tweets)
        reply_count = 0
        target_counts: dict[str, int] = defaultdict(int)

        for t in acct_tweets:
            targets = _parse_targets(t.get("text", ""))
            if targets:
                reply_count += 1
                for tgt in targets:
                    target_counts[tgt] += 1
                    target_accounts[tgt].add(account_id)

        top_targets = sorted(target_counts.items(), key=lambda x: x[1], reverse=True)[:top_n_targets]

        accounts.append({
            "account_id":  account_id,
            "handle":      handle_map[account_id],
            "total_tweets": total,
            "reply_ratio": round(reply_count / total, 2) if total else 0.0,
            "top_targets": [{"handle": h, "count": c} for h, c in top_targets],
        })

    # Shared targets: replied to by ≥2 distinct cell members
    shared_targets = [
        {
            "target":  target,
            "account_count": len(acct_set),
            "by":      sorted(handle_map.get(a, a) for a in acct_set),
        }
        for target, acct_set in target_accounts.items()
        if len(acct_set) >= 2
    ]
    shared_targets.sort(key=lambda x: x["account_count"], reverse=True)

    # Theme clusters across all historical replies (strip leading mention first)
    reply_tweets = [
        {**t, "author_id": t["account_id"], "text": _strip_leading_mention(t.get("text", ""))}
        for t in tweets
        if _parse_targets(t.get("text", ""))  # only actual replies
    ]
    cluster_result = cluster_mod.build_clusters(reply_tweets, min_cluster_size=1)

    # Filter out clusters whose representative text is too short to be
    # meaningful — short phrases like "K", "Racist", "Gun next time" match
    # too broadly at the semantic threshold and are noise, not coordination.
    meaningful_clusters = [
        c for c in cluster_result["clusters"]
        if len(c["representative_text"].split()) >= min_cluster_words
    ]

    return {
        "accounts":         accounts,
        "shared_targets":   shared_targets[:20],
        "theme_clusters":   meaningful_clusters,
        "self_repetitions": cluster_result["self_repetitions"],
    }


def detect_burst_window(
    tweets: list[dict],
    window_threshold_s: int = 3600,
) -> dict:
    """
    Find the largest group of tweets that fit inside window_threshold_s.

    O(n) two-pointer sliding window on sorted timestamps:
      - right pointer advances through every timestamp
      - left pointer shrinks the window whenever it exceeds the threshold
      - best_count tracks the widest window seen

    Returns:
        burst_window_s — actual span of the best window in seconds
        tweet_count    — number of tweets in that window
        window_start   — Unix timestamp of the first tweet in the burst
        window_end     — Unix timestamp of the last tweet in the burst
    """
    timestamps = sorted(
        t["posted_at"] for t in tweets if t.get("posted_at") is not None
    )
    if len(timestamps) < 2:
        return {
            "burst_window_s": 0,
            "tweet_count": len(timestamps),
            "window_start": timestamps[0] if timestamps else None,
            "window_end": timestamps[0] if timestamps else None,
        }

    left = 0
    best_count = 0
    best_start = timestamps[0]
    best_end = timestamps[0]

    for right in range(len(timestamps)):
        # Shrink from the left until the window fits within the threshold
        while timestamps[right] - timestamps[left] > window_threshold_s:
            left += 1

        count = right - left + 1
        if count > best_count:
            best_count = count
            best_start = timestamps[left]
            best_end = timestamps[right]

    return {
        "burst_window_s": int(best_end - best_start),
        "tweet_count": best_count,
        "window_start": best_start,
        "window_end": best_end,
    }


def detect_origin(accounts: list[dict], matched_tweets: list[dict]) -> str | None:
    """
    Return the account_id of the account whose matched tweet appeared first.
    """
    if not matched_tweets:
        return None

    valid = [t for t in matched_tweets if t.get("posted_at") is not None]
    if not valid:
        return None

    earliest = min(valid, key=lambda t: t["posted_at"])
    return earliest.get("account_id") or earliest.get("author_id")


def classify_pattern(
    cell_size: int,
    burst_window_s: int,
    bot_scores: list[float],
) -> str:
    """
    Classify the observed coordination pattern.

    Returns one of:
        COORDINATED_INAUTHENTIC
        BURST_AMPLIFICATION
        BOT_NETWORK
        ORGANIC_AMPLIFICATION
        INCONCLUSIVE
    """
    avg_score = statistics.mean(bot_scores) if bot_scores else 0.0

    if cell_size >= 10 and burst_window_s < 3600 and avg_score > 0.6:
        return "COORDINATED_INAUTHENTIC"
    if burst_window_s < 1800 and cell_size >= 5:
        return "BURST_AMPLIFICATION"
    if avg_score > 0.7:
        return "BOT_NETWORK"
    if cell_size >= 3:
        return "ORGANIC_AMPLIFICATION"
    return "INCONCLUSIVE"


def compute_confidence(
    cell_size: int,
    burst_window_s: int,
    bot_scores: list[float],
    match_count: int,
) -> float:
    """
    Compute overall confidence score 0.0–1.0.

    Contributions:
        cell size (max 0.30)
        burst tightness (max 0.25)
        avg bot score (max 0.30)
        match count (max 0.15)
    """
    score = 0.0

    score += min(cell_size / 20, 0.30)

    if burst_window_s > 0:
        score += max(0.0, 0.25 * (1.0 - burst_window_s / 86400))

    if bot_scores:
        score += statistics.mean(bot_scores) * 0.30

    score += min(match_count / 50, 0.15)

    return min(round(score, 4), 1.0)
