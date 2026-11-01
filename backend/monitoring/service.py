from __future__ import annotations

import logging
import threading

from backend.database.store import SQLiteStore
from backend.monitoring.system import collect_system_metrics

logger = logging.getLogger("mck.monitor")
_SAMPLE_INTERVALS = {"eco": 60, "balanced": 30, "performance": 15}


class SystemMonitor:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._memory_warning_active = False
        self._disk_warning_active = False
        self._oom_kill_count: int | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="system-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            settings = self.store.get_settings()
            try:
                metrics = collect_system_metrics()
                self.store.record_metrics(metrics)
                self._check_warnings(metrics, settings["memory_warning_percent"])
                self.store.prune(
                    settings["history_days"],
                    max_events=settings["log_size_mb"] * 2000,
                )
                current_oom_count = metrics["host"]["oom_kill_count"]
                if self._oom_kill_count is not None and current_oom_count is not None:
                    if current_oom_count > self._oom_kill_count:
                        self.store.add_event("ERROR", "oom_kill", "Linux reported a new out-of-memory kill")
                self._oom_kill_count = current_oom_count
            except Exception:
                logger.exception("System metrics sample failed")
            interval = _SAMPLE_INTERVALS.get(settings["mode"], 60)
            self._stop.wait(interval)

    def _check_warnings(self, metrics: dict, memory_threshold: int) -> None:
        memory_high = metrics["memory"]["usage_percent"] >= memory_threshold
        disk_high = metrics["disk"]["usage_percent"] >= 90
        if memory_high and not self._memory_warning_active:
            self.store.add_event("WARNING", "memory_warning", "RAM usage exceeded configured threshold")
        if disk_high and not self._disk_warning_active:
            self.store.add_event("WARNING", "disk_warning", "Root filesystem usage reached 90 percent")
        self._memory_warning_active = memory_high
        self._disk_warning_active = disk_high