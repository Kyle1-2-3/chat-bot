"""Improvement queue: answers students reported and questions the bot could not answer.

Kept in its own SQLite file (like the usage store) so deploys that reseed the
school database never wipe it. Stores the question and answer text, never IPs.
"""
from contextlib import closing
import sqlite3
from pathlib import Path

ISSUE_TYPES = {"unanswered", "incorrect", "outdated", "unclear", "other"}
STATUSES = {"open", "in_progress", "resolved"}


class FeedbackStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Feedback (
                feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL DEFAULT '',
                question TEXT NOT NULL,
                answer TEXT NOT NULL DEFAULT '',
                issue_type TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'student',
                status TEXT NOT NULL DEFAULT 'open',
                resolution_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        return conn

    def add(self, *, question, issue_type, answer="", details="", source="student", request_id=""):
        with closing(self.connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO Feedback(request_id, question, answer, issue_type, details, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (request_id, question, answer, issue_type, details, source))
            return cur.lastrowid

    def list(self, status="open", limit=100):
        sql, params = "SELECT * FROM Feedback", []
        if status != "all":
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY feedback_id DESC LIMIT ?"
        params.append(limit)
        with closing(self.connect()) as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def update(self, feedback_id, status, notes):
        """Returns False when no such item exists."""
        with closing(self.connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE Feedback SET status = ?, resolution_notes = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE feedback_id = ?", (status, notes, feedback_id))
            return cur.rowcount > 0
