CREATE TABLE IF NOT EXISTS accounts (
    id                    TEXT PRIMARY KEY,
    handle                TEXT NOT NULL,
    display_name          TEXT,
    created_at            INTEGER,
    followers             INTEGER,
    following             INTEGER,
    tweet_count           INTEGER,
    verified              INTEGER DEFAULT 0,
    default_profile_img   INTEGER DEFAULT 0,
    description           TEXT,
    bot_score             REAL,
    bot_score_computed_at INTEGER,
    profile_fetched_at    INTEGER,
    tweets_fetched_at     INTEGER
);

CREATE TABLE IF NOT EXISTS tweets (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    text        TEXT NOT NULL,
    text_hash   TEXT,
    posted_at   INTEGER,
    fetched_at  INTEGER,
    lang        TEXT
);

CREATE INDEX IF NOT EXISTS idx_tweets_text_hash  ON tweets(text_hash);
CREATE INDEX IF NOT EXISTS idx_tweets_posted_at  ON tweets(posted_at);
CREATE INDEX IF NOT EXISTS idx_tweets_account_id ON tweets(account_id);

CREATE TABLE IF NOT EXISTS investigations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    seed_text        TEXT NOT NULL,
    seed_tweet_id    TEXT REFERENCES tweets(id),
    status           TEXT DEFAULT 'PENDING',
    current_stage    TEXT,
    failed_at_stage  TEXT,
    failure_reason   TEXT,
    verdict          TEXT,
    confidence       REAL,
    pattern_type     TEXT,
    cell_size        INTEGER,
    burst_window_s   INTEGER,
    origin_account   TEXT REFERENCES accounts(id),
    operator_tz      TEXT,
    depth_used       TEXT,
    api_calls_used   INTEGER,
    ran_at           INTEGER,
    notes            TEXT,
    investigation_type TEXT DEFAULT 'TWEET',  -- TWEET | REPLIES | PROFILES
    last_accessed_at   INTEGER,               -- Unix ts of last cache hit or fresh run
    access_count       INTEGER DEFAULT 1,     -- increments on every cache hit
    search_source      TEXT DEFAULT 'API'     -- API | SCRAPER (which backend served the search)
);

CREATE TABLE IF NOT EXISTS cell_members (
    investigation_id  INTEGER REFERENCES investigations(id),
    account_id        TEXT REFERENCES accounts(id),
    role              TEXT,
    match_count       INTEGER,
    PRIMARY KEY (investigation_id, account_id)
);

CREATE TABLE IF NOT EXISTS tweet_matches (
    investigation_id  INTEGER REFERENCES investigations(id),
    tweet_id          TEXT REFERENCES tweets(id),
    similarity        REAL,
    match_type        TEXT,
    PRIMARY KEY (investigation_id, tweet_id)
);

CREATE TABLE IF NOT EXISTS api_call_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint         TEXT NOT NULL,
    called_at        INTEGER NOT NULL,
    investigation_id INTEGER REFERENCES investigations(id),
    cache_hit        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_api_calls_called_at ON api_call_log(called_at);

-- "narratives" = investigation campaign titles (e.g. "Vancouver Bot Campaign").
-- Each label acts as a named investigation series; investigations within a series
-- are numbered sequentially via investigation_narratives.seq.
CREATE TABLE IF NOT EXISTS narratives (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL UNIQUE,
    first_seen  INTEGER,
    last_seen   INTEGER,
    active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS investigation_narratives (
    investigation_id  INTEGER REFERENCES investigations(id),
    narrative_id      INTEGER REFERENCES narratives(id),
    -- seq: the sequential position of this investigation within the campaign (1, 2, 3…)
    seq               INTEGER DEFAULT NULL,
    -- occurrence: how many times this investigation has been re-associated with this label
    occurrence        INTEGER DEFAULT 1,
    PRIMARY KEY (investigation_id, narrative_id)
);

CREATE VIEW IF NOT EXISTS account_investigation_summary AS
SELECT
    a.id                                                           AS account_id,
    a.handle,
    a.bot_score,
    COUNT(cm.investigation_id)                                     AS investigation_count,
    GROUP_CONCAT(cm.investigation_id, ',')                         AS investigation_ids,
    MAX(i.ran_at)                                                  AS last_seen_at,
    SUM(CASE WHEN cm.role = 'ORIGIN' THEN 1 ELSE 0 END)           AS times_as_origin
FROM accounts a
LEFT JOIN cell_members cm ON cm.account_id = a.id
LEFT JOIN investigations i  ON i.id = cm.investigation_id
GROUP BY a.id;
