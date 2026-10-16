"""SQLite schema and connection handling. Times are integer Unix seconds.

Content lives in `summaries` and `jobs.video_id` only; both are purged after retention (M5).
Usage columns on `jobs` outlive it.
"""
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL,
  token_hash    TEXT NOT NULL UNIQUE,
  is_admin      INTEGER NOT NULL DEFAULT 0,
  daily_limit   INTEGER NOT NULL DEFAULT 5,
  weekly_limit  INTEGER NOT NULL DEFAULT 20,
  max_minutes   INTEGER NOT NULL DEFAULT 180,
  created_at    INTEGER NOT NULL,
  welcomed_at   INTEGER,
  revoked_at    INTEGER,
  last_seen_at  INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
  id                  INTEGER PRIMARY KEY,
  public_id           TEXT NOT NULL UNIQUE,
  user_id             INTEGER NOT NULL REFERENCES users(id),
  video_id            TEXT,
  status              TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
  cache_hit           INTEGER NOT NULL DEFAULT 0,
  coalesced_with      INTEGER REFERENCES jobs(id),
  attempts            INTEGER NOT NULL DEFAULT 0,
  not_before          INTEGER,
  lease_until         INTEGER,
  lease_id            TEXT,
  error_code          TEXT,
  input_tokens        INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
  output_tokens       INTEGER NOT NULL DEFAULT 0,
  cost_usd            REAL NOT NULL DEFAULT 0,
  model               TEXT,
  usage_at            INTEGER,
  email_status        TEXT CHECK (email_status IN ('pending', 'sending', 'sent', 'failed')),
  email_attempts      INTEGER NOT NULL DEFAULT 0,
  email_not_before    INTEGER,
  email_claimed_at    INTEGER,
  created_at          INTEGER NOT NULL,
  finished_at         INTEGER
);
CREATE INDEX IF NOT EXISTS jobs_user_created ON jobs (user_id, created_at);
CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS jobs_video ON jobs (video_id);
CREATE INDEX IF NOT EXISTS jobs_coalesced ON jobs (coalesced_with);

CREATE TABLE IF NOT EXISTS summaries (
  video_id    TEXT PRIMARY KEY,
  md          TEXT NOT NULL,
  title       TEXT NOT NULL,
  verdict     TEXT,
  created_at  INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  id                          INTEGER PRIMARY KEY CHECK (id = 1),
  paused                      INTEGER NOT NULL DEFAULT 0,
  global_daily_limit          INTEGER NOT NULL DEFAULT 40,
  global_daily_token_ceiling  INTEGER
);
INSERT OR IGNORE INTO settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS worker (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  last_seen  INTEGER,
  version    TEXT
);
INSERT OR IGNORE INTO worker (id) VALUES (1);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 10000')
    return conn


# Columns added after a database may already exist. CREATE TABLE IF NOT EXISTS won't add them.
ADDED = {
    'jobs': (('email_attempts', 'INTEGER NOT NULL DEFAULT 0'),
             ('email_not_before', 'INTEGER'),
             ('email_claimed_at', 'INTEGER')),
}


def init(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = connect(path)
    try:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.executescript(SCHEMA)
        for table, cols in ADDED.items():
            have = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
            for name, decl in cols:
                if name not in have:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
    finally:
        conn.close()


@contextmanager
def tx(conn):
    """A write transaction that takes the lock up front, so check-then-insert is atomic."""
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
    except BaseException:
        conn.execute('ROLLBACK')
        raise
    conn.execute('COMMIT')


def settings(conn):
    return conn.execute('SELECT * FROM settings WHERE id = 1').fetchone()
