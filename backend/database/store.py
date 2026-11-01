from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "eco",
    "memory_warning_percent": 85,
    "history_days": 14,
    "browser_name": "firefox-esr",
    "browser_auto_start": False,
    "browser_auto_restart": True,
    "process_check_interval_seconds": 5,
    "log_size_mb": 5,
    "timezone": "UTC",
}
_ALLOWED_SETTINGS = set(DEFAULT_SETTINGS)
_ALLOWED_MODES = {"eco", "balanced", "performance"}
_ALLOWED_BROWSERS = {"firefox-esr", "firefox", "chromium"}


class SQLiteStore:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            data_dir = Path(os.getenv("MCK_DATA_DIR", "data"))
            data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            data_dir.chmod(0o700)
            path = data_dir / "keeper.sqlite3"
        self.path = str(path)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not Path(self.path).exists():
                Path(self.path).touch(mode=0o600)
            os.chmod(self.path, 0o600)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    sampled_at INTEGER PRIMARY KEY,
                    cpu_percent REAL NOT NULL,
                    memory_percent REAL NOT NULL,
                    swap_percent REAL NOT NULL,
                    disk_percent REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS secrets (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            for key, value in DEFAULT_SETTINGS.items():
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
            connection.execute(
                "INSERT OR IGNORE INTO secrets(key, value) VALUES ('admin_password_hash', '')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO secrets(key, value) VALUES ('auth_epoch', '0')"
            )

    def initialize_admin_password_hash(self, password_hash: str | None) -> str | None:
        if password_hash:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "UPDATE secrets SET value=? WHERE key='admin_password_hash' AND value=''",
                    (password_hash,),
                )
        return self.admin_password_hash()

    def admin_password_hash(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM secrets WHERE key='admin_password_hash'"
            ).fetchone()
        return row["value"] or None

    def auth_epoch(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM secrets WHERE key='auth_epoch'").fetchone()
        return int(row["value"])

    def change_admin_password_hash(self, password_hash: str) -> int:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE secrets SET value=? WHERE key='admin_password_hash'", (password_hash,)
            )
            connection.execute(
                "UPDATE secrets SET value=CAST(value AS INTEGER) + 1 WHERE key='auth_epoch'"
            )
            row = connection.execute("SELECT value FROM secrets WHERE key='auth_epoch'").fetchone()
        return int(row["value"])

    def record_metrics(self, metrics: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO metrics VALUES (?, ?, ?, ?, ?)",
                (
                    metrics["sampled_at"],
                    metrics["cpu"]["usage_percent"],
                    metrics["memory"]["usage_percent"],
                    metrics["swap"]["usage_percent"],
                    metrics["disk"]["usage_percent"],
                ),
            )

    def recent_metrics(self, limit: int = 360) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM metrics ORDER BY sampled_at DESC LIMIT ?", (bounded_limit,)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_event(self, level: str, event_type: str, message: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO events(created_at, level, event_type, message) VALUES (?, ?, ?, ?)",
                (int(time.time()), level[:16], event_type[:48], message[:240]),
            )

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT created_at, level, event_type, message FROM events ORDER BY id DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_events(self) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM events")
            return cursor.rowcount

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        values = {row["key"]: json.loads(row["value"]) for row in rows}
        return DEFAULT_SETTINGS | values

    def validate_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        unknown = set(updates) - _ALLOWED_SETTINGS
        if unknown:
            raise ValueError(f"Thiết lập không được hỗ trợ: {', '.join(sorted(unknown))}.")
        current = self.get_settings()
        for key, value in updates.items():
            if key == "mode" and (not isinstance(value, str) or value not in _ALLOWED_MODES):
                raise ValueError("Chế độ phải là eco, balanced hoặc performance.")
            if key == "browser_name" and (
                not isinstance(value, str) or value not in _ALLOWED_BROWSERS
            ):
                raise ValueError("Trình duyệt không nằm trong danh sách hỗ trợ.")
            if key == "memory_warning_percent" and (type(value) is not int or not 50 <= value <= 99):
                raise ValueError("Ngưỡng RAM phải từ 50 đến 99.")
            if key == "history_days" and (type(value) is not int or not 1 <= value <= 90):
                raise ValueError("Lịch sử chỉ được giữ từ 1 đến 90 ngày.")
            if key == "process_check_interval_seconds" and (
                type(value) is not int or not 3 <= value <= 60
            ):
                raise ValueError("Chu kỳ kiểm tra phải từ 3 đến 60 giây.")
            if key == "log_size_mb" and (type(value) is not int or not 1 <= value <= 50):
                raise ValueError("Dung lượng log phải từ 1 đến 50 MB.")
            if key in {"browser_auto_start", "browser_auto_restart"} and type(value) is not bool:
                raise ValueError(f"{key} phải là true hoặc false.")
            if key == "timezone":
                if not isinstance(value, str) or len(value) > 64:
                    raise ValueError("Múi giờ không hợp lệ.")
                try:
                    ZoneInfo(value)
                except ZoneInfoNotFoundError as error:
                    raise ValueError("Múi giờ không được hệ thống hỗ trợ.") from error
            current[key] = value
        return current

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.validate_settings(updates)
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(key, json.dumps(value)) for key, value in updates.items()],
            )
        return current

    def prune(self, history_days: int, max_metrics: int = 5000, max_events: int = 5000) -> None:
        cutoff = int(time.time()) - max(1, history_days) * 86_400
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM metrics WHERE sampled_at < ?", (cutoff,))
            connection.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
            connection.execute(
                "DELETE FROM metrics WHERE sampled_at NOT IN "
                "(SELECT sampled_at FROM metrics ORDER BY sampled_at DESC LIMIT ?)",
                (max_metrics,),
            )
            connection.execute(
                "DELETE FROM events WHERE id NOT IN "
                "(SELECT id FROM events ORDER BY id DESC LIMIT ?)",
                (max(100, max_events),),
            )