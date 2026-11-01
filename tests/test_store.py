import logging
import os

import pytest

from backend.core.logging import clear_file_logs, configure_file_logging, read_recent_file_logs
from backend.database.store import SQLiteStore


def test_store_persists_metrics_events_and_settings(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    metrics = {
        "sampled_at": 123,
        "cpu": {"usage_percent": 12.5},
        "memory": {"usage_percent": 45.0},
        "swap": {"usage_percent": 2.0},
        "disk": {"usage_percent": 30.0},
    }
    store.record_metrics(metrics)
    store.add_event("INFO", "browser_started", "Browser started")
    updated = store.update_settings({"mode": "balanced", "memory_warning_percent": 90})

    assert store.recent_metrics()[0]["memory_percent"] == 45.0
    assert store.recent_events()[0]["event_type"] == "browser_started"
    assert updated["mode"] == "balanced"
    assert updated["memory_warning_percent"] == 90


def test_settings_reject_unknown_and_out_of_range_values(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    with pytest.raises(ValueError):
        store.update_settings({"shell_command": "id"})
    with pytest.raises(ValueError):
        store.update_settings({"memory_warning_percent": 100})
    with pytest.raises(ValueError):
        store.update_settings({"browser_name": "unapproved-browser"})


def test_rotating_file_log_uses_private_permissions_and_configured_limit(tmp_path) -> None:
    configure_file_logging(tmp_path / "private-logs", 2)
    logging.getLogger("mck.test").info("safe diagnostic event")
    log_path = tmp_path / "private-logs" / "keeper.log"
    assert "safe diagnostic event" in log_path.read_text()
    assert os.stat(log_path).st_mode & 0o777 == 0o600
    assert os.stat(log_path.parent).st_mode & 0o777 == 0o700
    handler = next(
        handler for handler in logging.getLogger("mck").handlers if hasattr(handler, "maxBytes")
    )
    assert handler.maxBytes == 2 * 1024 * 1024
    entries = read_recent_file_logs()
    assert entries[-1]["message"] == "safe diagnostic event"
    assert clear_file_logs() == 1
    assert read_recent_file_logs() == []