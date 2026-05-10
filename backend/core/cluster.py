"""
Tweet clustering for profile investigation.

Three passes:
  1. Exact  — group by normalised text hash, O(n)
  2. Candidate generation — inverted index on significant tokens, O(n × avg_words)
  3. Fuzzy/semantic — rapidfuzz on candidate pairs, O(candidates × comparison)

Same-author pairs are excluded from coordination clusters.
Self-repetition (one account posting the same text ≥2 times) is tracked separately
as self_repetitions and must NOT generate cell membership or coordination edges.

min_cluster_size: minimum number of DISTINCT authors beyond one required to flag as
coordination.  Default 2 means 3+ distinct authors must post the same text.
"""

import hashlib
import re
from collections import defaultdict

from rapidfuzz import fuzz

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "have", "from", "they",
    "will", "been", "were", "their", "there", "what", "when", "which",
    "who", "not", "are", "was", "but", "all", "can", "has", "its",
    "also", "more", "than", "then", "some", "about", "would", "into",
    "your", "just", "like", "very", "over", "such", "said", "each",
    "she", "him", "his", "her", "our", "out", "use", "how", "make",
    "may", "now", "any", "new", "get", "way", "see", "come", "could",
    "even", "back", "only", "know", "take", "year", "good", "much",
    "people", "time", "these", "other", "well", "need", "long",
    "https", "http",
}

MIN_TOKEN_LEN = 4


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _text_hash(text: str) -> str:
    return hashlib.md5(_normalize(text).encode()).hexdigest()


def _tokens(text: str) -> set[str]:
    """Alpha-only tokens, ≥ MIN_TOKEN_LEN chars, not a stopword."""
    return {
        t for t in re.findall(r"\b[a-z]+\b", text.lower())
        if len(t) >= MIN_TOKEN_LEN and t not in STOPWORDS
    }


def _find(parent: dict[str, str], x: str) -> str:
    if x not in parent:
        parent[x] = x
    root = x
    while parent[root] != root:
        root = parent[root]
    # Path compression
    node = x
    while parent[node] != root:
        parent[node], node = root, parent[node]
    return root


def _union(parent: dict[str, str], x: str, y: str) -> None:
    parent[_find(parent, x)] = _find(parent, y)


def build_clusters(
    tweets: list[dict],
    min_cluster_size: int = 2,
    fuzzy_threshold: float = 0.80,
    semantic_threshold: float = 0.65,
) -> dict:
    """
    tweets: list of {id, author_id, text, posted_at, ...}

    Returns:
        clusters — list of dicts:
            match_type: "EXACT" | "FUZZY" | "SEMANTIC"
            representative_text: str
            similarity: float
            members: [{tweet_id, author_id, posted_at}, ...]
        self_repetitions — {author_id: int}  near-duplicate count per account
    """
    if not tweets:
        return {"clusters": [], "self_repetitions": {}}

    tweet_by_id = {t["id"]: t for t in tweets}
    clusters: list[dict] = []
    self_reps: dict[str, int] = defaultdict(int)

    # ── Pass 1: exact clustering by normalised text hash ─────────────────────
    hash_groups: dict[str, list[dict]] = defaultdict(list)
    for t in tweets:
        hash_groups[_text_hash(t.get("text", ""))].append(t)

    exact_ids: set[str] = set()  # tweet IDs already placed in an exact cluster

    for group in hash_groups.values():
        if len(group) < 2:
            continue

        # Track same-author repeats within this exact hash group
        by_author: dict[str, list] = defaultdict(list)
        for t in group:
            by_author[t["author_id"]].append(t)
        for aid, ats in by_author.items():
            if len(ats) > 1:
                self_reps[aid] += len(ats) - 1

        distinct_authors = {t["author_id"] for t in group}
        if len(distinct_authors) >= min_cluster_size + 1:
            clusters.append({
                "match_type": "EXACT",
                "representative_text": group[0].get("text", ""),
                "similarity": 1.0,
                "members": [
                    {
                        "tweet_id": t["id"],
                        "author_id": t["author_id"],
                        "posted_at": t.get("posted_at"),
                    }
                    for t in group
                ],
            })
            for t in group:
                exact_ids.add(t["id"])

    # ── Pass 2: inverted index for fuzzy candidate pairs ─────────────────────
    # Tweets already in exact clusters are excluded — they won't gain new edges.
    token_index: dict[str, list[dict]] = defaultdict(list)
    for t in tweets:
        if t["id"] in exact_ids:
            continue
        for token in _tokens(t.get("text", "")):
            token_index[token].append(t)

    candidate_pairs: set[frozenset] = set()
    for token_tweets in token_index.values():
        if len(token_tweets) < 2:
            continue
        for i in range(len(token_tweets)):
            for j in range(i + 1, len(token_tweets)):
                a, b = token_tweets[i], token_tweets[j]
                if a["author_id"] == b["author_id"]:
                    continue  # same-author pairs excluded
                candidate_pairs.add(frozenset({a["id"], b["id"]}))

    # ── Pass 3: fuzzy / semantic matching on candidates ──────────────────────
    parent: dict[str, str] = {}
    pair_types: dict[frozenset, tuple[str, float]] = {}

    for pair in candidate_pairs:
        id_a, id_b = tuple(pair)
        text_a = tweet_by_id[id_a].get("text", "")
        text_b = tweet_by_id[id_b].get("text", "")

        ratio     = fuzz.ratio(text_a, text_b) / 100.0
        token_set = fuzz.token_set_ratio(text_a, text_b) / 100.0

        if max(ratio, token_set) >= fuzzy_threshold:
            _union(parent, id_a, id_b)
            pair_types[pair] = ("FUZZY", max(ratio, token_set))
        elif token_set >= semantic_threshold:
            _union(parent, id_a, id_b)
            pair_types[pair] = ("SEMANTIC", token_set)

    # Collect connected components
    components: dict[str, list[dict]] = defaultdict(list)
    for t in tweets:
        if t["id"] in parent:
            components[_find(parent, t["id"])].append(t)

    for group in components.values():
        if len(group) < 2:
            continue

        # Track same-author repeats within fuzzy cluster
        by_author = defaultdict(list)
        for t in group:
            by_author[t["author_id"]].append(t)
        for aid, ats in by_author.items():
            if len(ats) > 1:
                self_reps[aid] += len(ats) - 1

        distinct_authors = {t["author_id"] for t in group}
        if len(distinct_authors) < min_cluster_size + 1:
            continue

        # Cluster type: FUZZY if any matched pair is FUZZY, else SEMANTIC
        ids_in_group = {t["id"] for t in group}
        cluster_type = "SEMANTIC"
        max_sim = 0.0
        for pair, (mt, sim) in pair_types.items():
            if pair <= ids_in_group:
                if mt == "FUZZY":
                    cluster_type = "FUZZY"
                max_sim = max(max_sim, sim)

        clusters.append({
            "match_type": cluster_type,
            "representative_text": group[0].get("text", ""),
            "similarity": max_sim,
            "members": [
                {
                    "tweet_id": t["id"],
                    "author_id": t["author_id"],
                    "posted_at": t.get("posted_at"),
                }
                for t in group
            ],
        })

    return {"clusters": clusters, "self_repetitions": dict(self_reps)}
