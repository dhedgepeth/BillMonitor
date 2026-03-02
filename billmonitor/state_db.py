import sqlite3
from datetime import datetime, timezone


class StateDB:
    def __init__(self, db_path: str):
        self._db_path = db_path

    def initialize(self) -> None:
        """Create tables if they don't exist. Safe to call on every startup."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS processed_messages (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id   TEXT NOT NULL UNIQUE,
                    sender_email TEXT NOT NULL,
                    subject      TEXT,
                    processed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notified_bills (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_email TEXT NOT NULL,
                    due_date     TEXT NOT NULL,
                    amount       TEXT NOT NULL,
                    bill_name    TEXT NOT NULL,
                    notified_at  TEXT NOT NULL,
                    UNIQUE(sender_email, due_date)
                );

                CREATE INDEX IF NOT EXISTS idx_processed_message_id
                    ON processed_messages(message_id);

                CREATE INDEX IF NOT EXISTS idx_notified_bills_sender_date
                    ON notified_bills(sender_email, due_date);
            """)

    def is_processed(self, message_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_messages WHERE message_id = ?",
                (message_id,)
            ).fetchone()
            return row is not None

    def is_bill_notified(self, sender_email: str, due_date: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM notified_bills WHERE sender_email = ? AND due_date = ?",
                (sender_email, due_date)
            ).fetchone()
            return row is not None

    def record_processed(self, message_id: str, sender_email: str, subject: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO processed_messages
                   (message_id, sender_email, subject, processed_at)
                   VALUES (?, ?, ?, ?)""",
                (message_id, sender_email, subject, _now())
            )

    def record_notified_bill(
        self, sender_email: str, due_date: str, amount: str, bill_name: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO notified_bills
                   (sender_email, due_date, amount, bill_name, notified_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (sender_email, due_date, amount, bill_name, _now())
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
