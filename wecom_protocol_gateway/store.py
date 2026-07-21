import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


def event_key(payload: dict[str, Any]) -> str:
    guid = str(payload.get("guid") or "")
    identity = (
        payload.get("msgUniqueIdentifier")
        or payload.get("requestId")
        or payload.get("seq")
    )
    if identity not in (None, ""):
        return f"{guid}:{payload.get('cmd', '')}:{identity}"
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GatewayStore:
    def __init__(self, path: Path, state_key: str) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(state_key.encode("ascii"))
        self._lock = threading.Lock()
        self._initialize()

    def add_event(self, payload: dict[str, Any]) -> bool:
        key = event_key(payload)
        encrypted = self._fernet.encrypt(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        now = _utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO callback_events
                    (event_key, payload, status, attempts, created_at, updated_at)
                VALUES (?, ?, 'pending', 0, ?, ?)
                """,
                (key, encrypted, now, now),
            )
            return cursor.rowcount == 1

    def pending_events(self, limit: int = 100) -> list[tuple[str, dict[str, Any]]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_key, payload
                FROM callback_events
                WHERE status IN ('pending', 'failed')
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            (
                str(row["event_key"]),
                json.loads(self._fernet.decrypt(row["payload"]).decode("utf-8")),
            )
            for row in rows
        ]

    def mark_delivered(self, key: str) -> None:
        self._update_event(key, status="delivered", error=None)

    def mark_failed(self, key: str, error: str) -> None:
        self._update_event(key, status="failed", error=error[:500])

    def event_counts(self) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM callback_events GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def event_metadata(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_key, status, attempts, last_error, created_at, updated_at
                FROM callback_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_operation(
        self,
        *,
        method: str,
        guid: str,
        target_id: str | None,
        success: bool,
        result_code: int | None,
    ) -> None:
        target_hash = (
            hashlib.sha256(target_id.encode("utf-8")).hexdigest() if target_id else None
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO operations
                    (method, guid_hash, target_hash, success, result_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    method,
                    hashlib.sha256(guid.encode("utf-8")).hexdigest(),
                    target_hash,
                    int(success),
                    result_code,
                    _utc_now(),
                ),
            )

    def _update_event(self, key: str, *, status: str, error: str | None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE callback_events
                SET status = ?, attempts = attempts + 1, last_error = ?, updated_at = ?
                WHERE event_key = ?
                """,
                (status, error, _utc_now(), key),
            )

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS callback_events (
                    event_key TEXT PRIMARY KEY,
                    payload BLOB NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_callback_events_status_created
                    ON callback_events(status, created_at);
                CREATE TABLE IF NOT EXISTS operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method TEXT NOT NULL,
                    guid_hash TEXT NOT NULL,
                    target_hash TEXT,
                    success INTEGER NOT NULL,
                    result_code INTEGER,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
