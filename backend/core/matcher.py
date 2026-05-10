"""
Exact and fuzzy tweet matching using rapidfuzz.

Three match tiers:
  EXACT    — identical text (similarity = 1.0)
  FUZZY    — character-level near-copy, ratio >= 0.80
  SEMANTIC — shared vocabulary rewrite, token_set_ratio >= 0.65
             (same words, different sentence structure — more suspicious
             than copy-paste because it shows deliberate evasion effort)
"""

from rapidfuzz import fuzz


def exact_match(text1: str, text2: str) -> bool:
    return text1.strip().lower() == text2.strip().lower()


def find_matches(
    seed_text: str,
    tweets: list[dict],
    threshold: float = 0.80,
    semantic_threshold: float = 0.65,
) -> list[dict]:
    """
    Return tweets that match seed_text at any tier.

    Each returned dict extends the original tweet with:
        similarity  — float 0.0–1.0
        match_type  — "EXACT" | "FUZZY" | "SEMANTIC"
    """
    results: list[dict] = []
    for tweet in tweets:
        text = tweet.get("text", "")
        if exact_match(seed_text, text):
            results.append({**tweet, "similarity": 1.0, "match_type": "EXACT"})
            continue

        ratio     = fuzz.ratio(seed_text, text) / 100.0
        token_set = fuzz.token_set_ratio(seed_text, text) / 100.0

        if max(ratio, token_set) >= threshold:
            results.append({
                **tweet,
                "similarity": max(ratio, token_set),
                "match_type": "FUZZY",
            })
        elif token_set >= semantic_threshold:
            # Same vocabulary, reworded — flag as SEMANTIC
            results.append({
                **tweet,
                "similarity": token_set,
                "match_type": "SEMANTIC",
            })

    return results
