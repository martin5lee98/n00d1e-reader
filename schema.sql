-- schema.sql
--
-- D1 (SQLite) schema for the Chinese news/media aggregator.
--
-- Design notes:
-- - Scraping config (extraction method, per-column quirks like trust_description)
--   lives in Python (scrapers/registry.py), NOT here. This table stores content
--   and just enough metadata to drive scheduling and display.
-- - `author` is a single cleaned display string, not a structured list — see
--   scrapers/authors.py for why (space-separated Chinese names can't be split
--   reliably). `raw_author` keeps the original for future reprocessing.
-- - `extra` is a JSON text blob for fields we're not ready to model formally
--   (tags, audio_url, etc). Query into it with json_extract() if ever needed.
-- - Indexes below are corrected against the actual homepage, /latest, and
--   /category query shapes (see conversation) — not guessed in isolation.

CREATE TABLE columns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site TEXT NOT NULL,                -- 'thepaper', 'yicai', 'sspai', 'tencent_tech', 'ftchinese', 'initium'
  column_key TEXT NOT NULL UNIQUE,   -- matches the Python registry key, e.g. 'thepaper-sixiang-shichang'
  outlet_name TEXT NOT NULL,         -- '第一财经' — display name
  column_name TEXT,                  -- '阅读周刊' — nullable, some sources are outlet-level not column-level
  category TEXT NOT NULL,            -- 'culture' | 'tech' | 'society' | 'international' | 'finance' | 'opinion' | 'life'
  source_url TEXT NOT NULL,          -- column page, for the "outlet/column" header link
  fetch_interval_minutes INTEGER NOT NULL DEFAULT 60,
  active INTEGER NOT NULL DEFAULT 1, -- boolean
  last_fetched_at TEXT,              -- ISO8601
  last_fetch_status TEXT,            -- 'ok' | 'error'
  last_fetch_error TEXT,             -- last error message, for the stale-column monitor
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  column_id INTEGER NOT NULL REFERENCES columns(id),
  url TEXT NOT NULL UNIQUE,          -- normalized, dedup key (UNIQUE also gives us a free index for ON CONFLICT)
  title TEXT NOT NULL,
  description TEXT,                  -- null when trust_description=False upstream, or source has no real summary
  image_url TEXT,
  author TEXT,                       -- cleaned display string, e.g. '龚思量、杨小舟'
  raw_author TEXT,                   -- original string as scraped, kept for reprocessing
  published_at TEXT,                 -- ISO8601, null if source doesn't expose it
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),  -- first-seen time; fallback sort key;
                                                         -- deliberately NOT updated on re-scrape of an
                                                         -- already-known article (see upsert logic) so
                                                         -- "column last updated" reflects real new content
  extra TEXT,                        -- JSON blob: tags, audio_url, source node description, etc
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Powers:
--   - homepage ranked CTE: PARTITION BY column_id ORDER BY published_at/fetched_at
--   - /latest ranked CTE: same partition/order, per column
--   - /latest column_recency aggregate: GROUP BY column_id (column_id leading
--     column makes this efficient even though the index wasn't built for MAX())
--   - column page pagination: WHERE column_id = ? ORDER BY published_at DESC
CREATE INDEX idx_articles_column_sort
  ON articles (column_id, published_at DESC, fetched_at DESC);

-- Powers:
--   - /category/{slug} filtering (WHERE c.category = ? AND c.active = 1)
--   - homepage's per-category grouping when pulling the active column list
CREATE INDEX idx_columns_category ON columns (category, active);

-- Note: no separate index needed for the articles.url dedup lookup used by
-- ON CONFLICT(url) in the upsert — the UNIQUE constraint on url already
-- creates one automatically.
