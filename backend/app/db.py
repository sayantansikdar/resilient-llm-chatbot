import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    metadata    TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ChatStore:
    """Session history in SQLite.

    Every call opens its own short-lived connection and runs in a worker thread,
    so the event loop never blocks on disk I/O. SQLite handles this fine at chat volumes.
    """

    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit on success, rollback on error
                yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    async def ping(self) -> bool:
        def _ping() -> bool:
            with self._connect() as conn:
                conn.execute("SELECT 1 FROM messages LIMIT 1").fetchall()
            return True

        try:
            return await asyncio.to_thread(_ping)
        except sqlite3.Error:
            return False

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        def _get():
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT session_id, system_prompt FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            return dict(row) if row else None

        return await asyncio.to_thread(_get)

    async def get_messages(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Oldest first. With `limit`, only the most recent `limit` messages."""

        def _get():
            with self._connect() as conn:
                if limit is None:
                    rows = conn.execute(
                        "SELECT role, content, metadata, created_at FROM messages "
                        "WHERE session_id = ? ORDER BY id",
                        (session_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT role, content, metadata, created_at FROM ("
                        "  SELECT id, role, content, metadata, created_at FROM messages "
                        "  WHERE session_id = ? ORDER BY id DESC LIMIT ?"
                        ") ORDER BY id",
                        (session_id, limit),
                    ).fetchall()
            out = []
            for row in rows:
                item = {"role": row["role"], "content": row["content"], "created_at": row["created_at"]}
                if row["metadata"]:
                    item["metadata"] = json.loads(row["metadata"])
                out.append(item)
            return out

        return await asyncio.to_thread(_get)

    async def save_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
        system_prompt: str | None,
        update_system_prompt: bool,
    ) -> None:
        """Store one user/assistant pair atomically, creating the session if needed."""

        def _save():
            now = utc_now()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO sessions (session_id, system_prompt, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at",
                    (session_id, system_prompt, now, now),
                )
                if update_system_prompt:
                    conn.execute(
                        "UPDATE sessions SET system_prompt = ? WHERE session_id = ?",
                        (system_prompt, session_id),
                    )
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                    "VALUES (?, 'user', ?, NULL, ?)",
                    (session_id, user_message, now),
                )
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                    "VALUES (?, 'assistant', ?, ?, ?)",
                    (session_id, assistant_message, json.dumps(metadata), utc_now()),
                )

        await asyncio.to_thread(_save)
