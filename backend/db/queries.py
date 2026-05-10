import hashlib
import re
import time
from datetime import datetime, timezone
import aiosqlite
from typing import Any


def _hash_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.md5(normalized.encode()).hexdigest()


async def upsert_account(db_path: str, account: dict) -> None:
    now = int(time.time())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO accounts (
                id, handle, display_name, created_at, followers, following,
                tweet_count, verified, default_profile_img, description,
                bot_score, bot_score_computed_at, profile_fetched_at, tweets_fetched_at
            ) VALUES (
                :id, :handle, :display_name, :created_at, :followers, :following,
                :tweet_count, :verified, :default_profile_img, :description,
                :bot_score, :bot_score_computed_at, :profile_fetched_at, :tweets_fetched_at
            )
            ON CONFLICT(id) DO UPDATE SET
                handle               = excluded.handle,
                display_name         = excluded.display_name,
                created_at           = COALESCE(excluded.created_at, accounts.created_at),
                followers            = COALESCE(excluded.followers, accounts.followers),
                following            = COALESCE(excluded.following, accounts.following),
                tweet_count          = COALESCE(excluded.tweet_count, accounts.tweet_count),
                verified             = COALESCE(excluded.verified, accounts.verified),
                default_profile_img  = COALESCE(excluded.default_profile_img, accounts.default_profile_img),
                description          = COALESCE(excluded.description, accounts.description),
                bot_score            = COALESCE(excluded.bot_score, accounts.bot_score),
                bot_score_computed_at= COALESCE(excluded.bot_score_computed_at, accounts.bot_score_computed_at),
                profile_fetched_at   = excluded.profile_fetched_at,
                tweets_fetched_at    = COALESCE(excluded.tweets_fetched_at, accounts.tweets_fetched_at)
            """,
            {
                "id": account["id"],
                "handle": account.get("handle", "unknown"),
                "display_name": account.get("display_name"),
                "created_at": account.get("created_at"),
                "followers": account.get("followers"),
                "following": account.get("following"),
                "tweet_count": account.get("tweet_count"),
                "verified": int(account.get("verified", False)),
                "default_profile_img": int(account.get("default_profile_img", False)),
                "description": account.get("description"),
                "bot_score": account.get("bot_score"),
                "bot_score_computed_at": now if "bot_score" in account else None,
                "profile_fetched_at": now if account.get("profile_fetched") else None,
                "tweets_fetched_at": now if account.get("tweets_fetched") else None,
            },
        )
        await db.commit()


async def upsert_tweet(db_path: str, tweet: dict) -> None:
    now = int(time.time())
    text = tweet.get("text", "")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO tweets (id, account_id, text, text_hash, posted_at, fetched_at, lang)
            VALUES (:id, :account_id, :text, :text_hash, :posted_at, :fetched_at, :lang)
            ON CONFLICT(id) DO NOTHING
            """,
            {
                "id": tweet["id"],
                "account_id": tweet.get("account_id") or tweet.get("author_id"),
                "text": text,
                "text_hash": _hash_text(text),
                "posted_at": tweet.get("posted_at"),
                "fetched_at": now,
                "lang": tweet.get("lang"),
            },
        )
        await db.commit()


_DEPTH_RANK = {"QUICK": 1, "STANDARD": 2, "DEEP": 3}


async def find_cached_investigation(
    db_path: str,
    seed_text: str,
    investigation_type: str,
    requested_depth: str,
) -> dict | None:
    """
    Return the most recent COMPLETE investigation for the same seed_text +
    investigation_type whose depth_used is >= requested_depth.
    Returns None if the caller should run fresh.
    """
    requested_rank = _DEPTH_RANK.get(requested_depth, 2)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM investigations
            WHERE seed_text = ?
              AND investigation_type = ?
              AND status = 'COMPLETE'
            ORDER BY ran_at DESC
            LIMIT 10
            """,
            (seed_text.strip(), investigation_type),
        )
        rows = await cursor.fetchall()
        for row in rows:
            cached_rank = _DEPTH_RANK.get(row["depth_used"], 2)
            if cached_rank >= requested_rank:
                now = int(time.time())
                await db.execute(
                    """
                    UPDATE investigations
                    SET last_accessed_at = ?,
                        access_count = COALESCE(access_count, 1) + 1
                    WHERE id = ?
                    """,
                    (now, row["id"]),
                )
                await db.commit()
                return dict(row)
        return None


async def create_investigation(
    db_path: str,
    seed_text: str,
    depth: str,
    seed_tweet_id: str | None = None,
    investigation_type: str = "TWEET",
) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO investigations (seed_text, seed_tweet_id, status, depth_used, investigation_type)
            VALUES (?, ?, 'PENDING', ?, ?)
            """,
            (seed_text, seed_tweet_id, depth, investigation_type),
        )
        await db.commit()
        return cursor.lastrowid


async def update_investigation(db_path: str, investigation_id: int, **kwargs) -> None:
    if not kwargs:
        return
    allowed = {
        "status", "current_stage", "failed_at_stage", "failure_reason",
        "verdict", "confidence", "pattern_type", "cell_size", "burst_window_s",
        "origin_account", "operator_tz", "depth_used", "api_calls_used",
        "ran_at", "notes", "seed_tweet_id", "investigation_type",
        "last_accessed_at", "access_count", "search_source",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    sets = ", ".join(f"{k} = :{k}" for k in filtered)
    filtered["_id"] = investigation_id
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE investigations SET {sets} WHERE id = :_id", filtered
        )
        await db.commit()


async def get_investigation(db_path: str, investigation_id: int) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM investigations WHERE id = ?", (investigation_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_investigations(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM investigations ORDER BY id DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_cell_member(
    db_path: str,
    investigation_id: int,
    account_id: str,
    role: str,
    match_count: int,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO cell_members (investigation_id, account_id, role, match_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(investigation_id, account_id) DO UPDATE SET
                role = excluded.role,
                match_count = excluded.match_count
            """,
            (investigation_id, account_id, role, match_count),
        )
        await db.commit()


async def add_tweet_match(
    db_path: str,
    investigation_id: int,
    tweet_id: str,
    similarity: float,
    match_type: str,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO tweet_matches (investigation_id, tweet_id, similarity, match_type)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(investigation_id, tweet_id) DO NOTHING
            """,
            (investigation_id, tweet_id, similarity, match_type),
        )
        await db.commit()


async def get_investigation_report(db_path: str, investigation_id: int) -> dict | None:
    """Full report: investigation + cell members + their account profiles + tweet matches."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        inv_cursor = await db.execute(
            "SELECT * FROM investigations WHERE id = ?", (investigation_id,)
        )
        inv_row = await inv_cursor.fetchone()
        if not inv_row:
            return None
        investigation = dict(inv_row)

        members_cursor = await db.execute(
            """
            SELECT cm.*, a.handle, a.display_name, a.bot_score, a.followers,
                   a.following, a.created_at, a.verified, a.default_profile_img,
                   a.description, a.tweet_count,
                   ais.investigation_count, ais.times_as_origin, ais.investigation_ids
            FROM cell_members cm
            JOIN accounts a ON a.id = cm.account_id
            LEFT JOIN account_investigation_summary ais ON ais.account_id = cm.account_id
            WHERE cm.investigation_id = ?
            """,
            (investigation_id,),
        )
        members = [dict(r) for r in await members_cursor.fetchall()]

        matches_cursor = await db.execute(
            """
            SELECT tm.*, t.text, t.posted_at, t.account_id, t.lang
            FROM tweet_matches tm
            JOIN tweets t ON t.id = tm.tweet_id
            WHERE tm.investigation_id = ?
            ORDER BY tm.similarity DESC
            """,
            (investigation_id,),
        )
        matches = [dict(r) for r in await matches_cursor.fetchall()]

        return {
            "investigation": investigation,
            "cell_members": members,
            "tweet_matches": matches,
        }


async def get_tweet(db_path: str, tweet_id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tweets WHERE id = ?", (tweet_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_account(db_path: str, account_id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_cell_member_tweets(db_path: str, investigation_id: int) -> list[dict]:
    """
    Return all stored tweets for cell members of an investigation.
    Used for profile analysis — no API calls, pure DB read.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT t.id, t.account_id, t.text, t.posted_at, t.lang,
                   a.handle
            FROM tweets t
            JOIN cell_members cm ON cm.account_id = t.account_id
                                 AND cm.investigation_id = ?
            JOIN accounts a ON a.id = t.account_id
            ORDER BY t.account_id, t.posted_at DESC
            """,
            (investigation_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_tweets_by_account_ids(db_path: str, account_ids: list[str]) -> list[dict]:
    """Return all cached tweets for a list of account IDs."""
    if not account_ids:
        return []
    placeholders = ",".join("?" * len(account_ids))
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT id, account_id, text, posted_at, lang FROM tweets WHERE account_id IN ({placeholders})",
            account_ids,
        )
        rows = await cursor.fetchall()
        return [
            {
                "id":        r["id"],
                "author_id": r["account_id"],
                "text":      r["text"],
                "posted_at": r["posted_at"],
                "lang":      r["lang"],
            }
            for r in rows
        ]


async def log_api_call(
    db_path: str,
    endpoint: str,
    investigation_id: int | None = None,
    cache_hit: bool = False,
) -> None:
    now = int(time.time())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO api_call_log (endpoint, called_at, investigation_id, cache_hit)
            VALUES (?, ?, ?, ?)
            """,
            (endpoint, now, investigation_id, int(cache_hit)),
        )
        await db.commit()


async def list_top_investigations(
    db_path: str,
    verdict: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Return COMPLETE investigations ranked by confidence DESC, cell_size DESC.
    Optionally filter by verdict (COORDINATED | UNCERTAIN | ORGANIC).
    """
    where = "WHERE status = 'COMPLETE'"
    params: list = []
    if verdict:
        where += " AND verdict = ?"
        params.append(verdict)
    params.extend([limit, offset])

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT i.id, i.seed_text, i.verdict, i.confidence, i.pattern_type,
                   i.cell_size, i.burst_window_s, i.origin_account,
                   i.api_calls_used, i.depth_used, i.ran_at, i.investigation_type,
                   i.last_accessed_at, i.access_count, i.search_source,
                   GROUP_CONCAT(n.label || '~' || COALESCE(inv_n.seq, ''), '|||') AS narrative_labels
            FROM investigations i
            LEFT JOIN investigation_narratives inv_n ON inv_n.investigation_id = i.id
            LEFT JOIN narratives n ON n.id = inv_n.narrative_id
            {where}
            GROUP BY i.id
            ORDER BY i.confidence DESC, i.cell_size DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            row = dict(r)
            raw = row.pop("narrative_labels", None)
            labels = []
            if raw:
                for entry in raw.split("|||"):
                    if "~" in entry:
                        lbl, seq_str = entry.split("~", 1)
                        labels.append({"label": lbl, "seq": int(seq_str) if seq_str else None})
                    else:
                        labels.append({"label": entry, "seq": None})
            row["narrative_labels"] = labels
            result.append(row)
        return result


async def label_investigation(db_path: str, investigation_id: int, label: str) -> dict:
    """
    Attach a narrative label to an investigation.
    Creates the narrative if it doesn't exist, upserts the link.
    Returns the narrative row.
    """
    now = int(time.time())
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Find or create the narrative
        cursor = await db.execute(
            "SELECT id FROM narratives WHERE label = ?", (label,)
        )
        row = await cursor.fetchone()
        if row:
            narrative_id = row["id"]
            await db.execute(
                "UPDATE narratives SET last_seen = ?, active = 1 WHERE id = ?",
                (now, narrative_id),
            )
        else:
            cursor = await db.execute(
                "INSERT INTO narratives (label, first_seen, last_seen) VALUES (?, ?, ?)",
                (label, now, now),
            )
            narrative_id = cursor.lastrowid

        # Link investigation → narrative, assigning the next seq number in the series
        # seq = number of investigations already linked to this narrative + 1
        cur2 = await db.execute(
            "SELECT COUNT(*) FROM investigation_narratives WHERE narrative_id = ?",
            (narrative_id,),
        )
        count_row = await cur2.fetchone()
        next_seq = (count_row[0] if count_row else 0) + 1

        await db.execute(
            """
            INSERT INTO investigation_narratives (investigation_id, narrative_id, seq, occurrence)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(investigation_id, narrative_id) DO UPDATE SET
                occurrence = occurrence + 1
            """,
            (investigation_id, narrative_id, next_seq),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM narratives WHERE id = ?", (narrative_id,)
        )
        return dict(await cursor.fetchone())


async def get_investigation_labels(db_path: str, investigation_id: int) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT n.id, n.label, n.first_seen, n.last_seen, n.active,
                   inv_n.seq, inv_n.occurrence
            FROM investigation_narratives inv_n
            JOIN narratives n ON n.id = inv_n.narrative_id
            WHERE inv_n.investigation_id = ?
            ORDER BY n.label
            """,
            (investigation_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_investigation_evidence(db_path: str, investigation_id: int) -> dict:
    """
    Build the Evidence panel data for an investigation.

    Returns:
      accounts: per-account dossier including tweet_rate, ff_ratio,
                weapon_account flag, top repeated phrases, and recent tweets
      direct_attacks: tweets from cell members that directly mention the
                      seed tweet author (if resolvable)
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Get investigation for context
        inv_cur = await db.execute(
            "SELECT seed_text, seed_tweet_id, investigation_type FROM investigations WHERE id = ?",
            (investigation_id,)
        )
        inv = await inv_cur.fetchone()
        if not inv:
            return {"accounts": [], "direct_attacks": []}
        inv = dict(inv)

        # Get cell members + account data
        members_cur = await db.execute(
            """
            SELECT cm.account_id, cm.role, cm.match_count,
                   a.handle, a.followers, a.following, a.tweet_count,
                   a.bot_score, a.created_at, a.description
            FROM cell_members cm
            JOIN accounts a ON a.id = cm.account_id
            WHERE cm.investigation_id = ?
            ORDER BY a.bot_score DESC
            """,
            (investigation_id,)
        )
        members = [dict(r) for r in await members_cur.fetchall()]

        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).timestamp()

        accounts = []
        for m in members:
            age_days = max((now_ts - (m["created_at"] or now_ts)) / 86400, 1)
            tweet_rate = round((m["tweet_count"] or 0) / age_days, 1)
            ff_ratio   = round((m["following"] or 0) / max(m["followers"] or 0, 1), 2)
            # Weapon account: near-zero followers, very few total tweets, low engagement
            weapon = (
                (m["followers"] or 0) < 20 and
                (m["tweet_count"] or 0) < 50
            )

            # Stored tweets for this account in this investigation's context
            tweets_cur = await db.execute(
                """
                SELECT t.id, t.text, t.posted_at
                FROM tweets t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.handle = ?
                ORDER BY t.posted_at DESC
                LIMIT 100
                """,
                (m["handle"],)
            )
            raw_tweets = [dict(r) for r in await tweets_cur.fetchall()]

            # Find repeated phrases (group by text_hash, count > 1)
            rep_cur = await db.execute(
                """
                SELECT t.text, COUNT(*) as cnt
                FROM tweets t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.handle = ?
                GROUP BY t.text_hash
                HAVING cnt > 1
                ORDER BY cnt DESC
                LIMIT 5
                """,
                (m["handle"],)
            )
            repeated = [{"text": r["text"], "count": r["cnt"]} for r in await rep_cur.fetchall()]

            # 5 most recent tweets for display
            recent = [
                {"text": t["text"], "posted_at": t["posted_at"]}
                for t in raw_tweets[:5]
            ]

            accounts.append({
                "handle":      m["handle"],
                "role":        m["role"],
                "bot_score":   m["bot_score"],
                "followers":   m["followers"],
                "following":   m["following"],
                "tweet_count": m["tweet_count"],
                "created_at":  m["created_at"],
                "description": m["description"],
                "tweet_rate":  tweet_rate,
                "ff_ratio":    ff_ratio,
                "weapon_account": weapon,
                "repeated_phrases": repeated,
                "recent_tweets": recent,
            })

        # Direct attacks: tweets mentioning the seed author handle
        # Try to extract handle from seed tweet URL or seed text
        seed_handle = None
        seed_text = inv.get("seed_text", "")
        # x.com/handle/status/... pattern
        import re
        m_url = re.search(r"(?:twitter\.com|x\.com)/([^/]+)/status/", seed_text)
        if m_url:
            seed_handle = m_url.group(1).lower()

        direct_attacks = []
        if seed_handle:
            cell_handles = [a["handle"] for a in accounts]
            placeholders = ",".join("?" * len(cell_handles))
            atk_cur = await db.execute(
                f"""
                SELECT t.text, t.posted_at, a.handle as author
                FROM tweets t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.handle IN ({placeholders})
                  AND (LOWER(t.text) LIKE ? OR LOWER(t.text) LIKE ?)
                ORDER BY t.posted_at DESC
                """,
                cell_handles + [f"%@{seed_handle}%", f"%{seed_handle}%"]
            )
            direct_attacks = [dict(r) for r in await atk_cur.fetchall()]

        return {
            "accounts":       accounts,
            "direct_attacks": direct_attacks,
            "seed_handle":    seed_handle,
        }


async def list_narratives(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, label FROM narratives WHERE active = 1 ORDER BY label"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def count_calls_this_month(db_path: str) -> int:
    month_start = int(
        datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
    )
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM api_call_log WHERE called_at >= ? AND cache_hit = 0",
            (month_start,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_repeat_offenders(
    db_path: str, min_appearances: int = 3
) -> list[dict]:
    """
    Return accounts that appear as cell members in >= min_appearances investigations,
    ordered by investigation_count DESC.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT a.id, a.handle, a.display_name, a.bot_score,
                   a.followers, a.following, a.tweet_count, a.verified,
                   ais.investigation_count, ais.times_as_origin,
                   ais.investigation_ids, ais.last_seen_at
            FROM account_investigation_summary ais
            JOIN accounts a ON a.id = ais.account_id
            WHERE ais.investigation_count >= ?
            ORDER BY ais.investigation_count DESC
            """,
            (min_appearances,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def count_calls_for_investigation(db_path: str, investigation_id: int) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM api_call_log WHERE investigation_id = ? AND cache_hit = 0",
            (investigation_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def count_calls_this_window(db_path: str, endpoint: str) -> int:
    now = int(time.time())
    window_start = now - 15 * 60
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM api_call_log
            WHERE endpoint = ? AND called_at >= ? AND cache_hit = 0
            """,
            (endpoint, window_start),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
