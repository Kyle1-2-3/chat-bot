"""Small, persistent counters shared by all workers on one server.

Keep this database separate from the reseeded school database. No questions,
answers, API keys, or raw IP addresses belong here.
"""
from contextlib import closing
import secrets
import sqlite3
from pathlib import Path


class UsageStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=2)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS counters "
                         "(bucket TEXT PRIMARY KEY, used INTEGER NOT NULL, resets INTEGER NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            return conn
        except Exception:
            conn.close()
            raise

    def signing_key(self):
        """A stable, server-only cookie key, shared across workers and restarts."""
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT OR IGNORE INTO settings VALUES ('cookie_key', ?)",
                         (secrets.token_hex(32),))
            return conn.execute("SELECT value FROM settings WHERE name='cookie_key'").fetchone()[0]

    def reserve(self, buckets, now):
        """Atomically increment all (key, limit, reset timestamp) buckets.

        Returns 0 when allowed or the number of seconds until retry. A rejected
        reservation increments nothing. Limit 0 disables that bucket.
        """
        buckets = [(key, limit, resets) for key, limit, resets in buckets if limit > 0]
        if not buckets:
            return 0
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM counters WHERE resets <= ?", (now,))
            retry_after = 0
            for key, limit, resets in buckets:
                row = conn.execute("SELECT used FROM counters WHERE bucket=?", (key,)).fetchone()
                if row and row[0] >= limit:
                    retry_after = max(retry_after, resets - now)
            if retry_after:
                return max(1, int(retry_after))
            for key, limit, resets in buckets:
                conn.execute("INSERT INTO counters VALUES (?, 1, ?) "
                             "ON CONFLICT(bucket) DO UPDATE SET used=used+1", (key, resets))
        return 0


class UsageUnavailable(Exception):
    """Do not make an unmetered model call if the counter store fails."""


class DailyBudgetReached(Exception):
    pass
