"""Manage a supported browser process without shell execution."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import psutil

logger = logging.getLogger("mck.browser")
_MESSENGER_URL = "https://www.messenger.com/"
_SUPPORTED = {"firefox-esr": "firefox-esr", "firefox": "firefox", "chromium": "chromium"}


class BrowserManager:
    def __init__(
        self,
        profile_dir: Path | None = None,
        browser_name: str | None = None,
        auto_restart: bool | None = None,
        check_interval: int = 5,
        event_callback: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.browser_name = browser_name or os.getenv("BROWSER_NAME", "firefox-esr")
        self.executable = os.getenv("BROWSER_EXECUTABLE") or _SUPPORTED.get(self.browser_name, "")
        self.profile_dir = profile_dir or Path(os.getenv("BROWSER_PROFILE_DIR", "data/browser-profile"))
        self._process: subprocess.Popen[bytes] | None = None
        self._started_at: float | None = None
        self._version: str | None = None
        self._restart_count = 0
        self._should_run = False
        self._lock = threading.RLock()
        self._monitor: threading.Thread | None = None
        self._stop_monitor = threading.Event()
        self._auto_restart = (
            auto_restart
            if auto_restart is not None
            else os.getenv("BROWSER_AUTO_RESTART", "true").lower() == "true"
        )
        self._check_interval = max(3, min(check_interval, 60))
        self._event_callback = event_callback

    def _record(self, level: int, event_type: str, message: str) -> None:
        logger.log(level, "%s", message)
        if self._event_callback:
            self._event_callback(logging.getLevelName(level), event_type, message)

    def configure(self, browser_name: str, auto_restart: bool, check_interval: int) -> None:
        if browser_name not in _SUPPORTED:
            raise ValueError("Trình duyệt không nằm trong danh sách hỗ trợ.")
        with self._lock:
            if self._process and self._process.poll() is None and browser_name != self.browser_name:
                raise RuntimeError("Dừng trình duyệt trước khi đổi lựa chọn browser.")
            if browser_name != self.browser_name:
                self.browser_name = browser_name
                self.executable = os.getenv("BROWSER_EXECUTABLE") or _SUPPORTED[browser_name]
                self._version = None
            self._auto_restart = auto_restart
            self._check_interval = max(3, min(check_interval, 60))

    def _find_executable(self) -> str | None:
        configured = self.executable
        if not configured:
            return None
        if os.path.isabs(configured):
            return configured if os.path.isfile(configured) and os.access(configured, os.X_OK) else None
        return shutil.which(configured)

    def _read_version(self, executable: str) -> str | None:
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            return (result.stdout or result.stderr).strip()[:160] or None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _command(self, executable: str) -> list[str]:
        if self.browser_name.startswith("firefox"):
            command = [executable, "--no-remote", "--profile", str(self.profile_dir)]
            if os.getenv("BROWSER_HEADLESS", "false").lower() == "true":
                command.append("--headless")
            return [*command, _MESSENGER_URL]
        command = [
            executable,
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if os.getenv("BROWSER_HEADLESS", "false").lower() == "true":
            command.append("--headless=new")
        return [*command, _MESSENGER_URL]

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._should_run = True
                return self.status()
            executable = self._find_executable()
            if not executable:
                raise RuntimeError(f"Không tìm thấy trình duyệt được cấu hình: {self.browser_name}.")
            self.profile_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.profile_dir.chmod(0o700)
            self._version = self._read_version(executable)
            try:
                self._process = subprocess.Popen(
                    self._command(executable),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as error:
                raise RuntimeError("Không thể khởi chạy trình duyệt.") from error
            self._started_at = time.time()
            self._should_run = True
            self._record(
                logging.INFO,
                "browser_started",
                f"Browser started: name={self.browser_name} pid={self._process.pid}",
            )
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._should_run = False
            process = self._process
            if process:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                self._record(
                    logging.INFO,
                    "browser_stopped",
                    f"Browser stopped: name={self.browser_name} pid={process.pid}",
                )
            self._process = None
            self._started_at = None
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            running = process is not None and process.poll() is None
            rss_bytes = 0
            cpu_percent = 0.0
            if running and process:
                try:
                    root = psutil.Process(process.pid)
                    descendants = [root, *root.children(recursive=True)]
                    for child in descendants:
                        try:
                            rss_bytes += child.memory_info().rss
                            cpu_percent += child.cpu_percent(interval=None)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    running = False
            return {
                "name": self.browser_name,
                "version": self._version,
                "installed": self._find_executable() is not None,
                "running": running,
                "pid": process.pid if running and process else None,
                "memory_bytes": rss_bytes,
                "cpu_percent": round(cpu_percent, 1),
                "uptime_seconds": max(0, int(time.time() - self._started_at))
                if running and self._started_at
                else 0,
                "restart_count": self._restart_count,
                "profile_persistent": True,
                "auto_restart": self._auto_restart,
            }

    def start_monitor(self) -> None:
        if self._monitor and self._monitor.is_alive():
            return
        self._stop_monitor.clear()
        self._monitor = threading.Thread(target=self._monitor_loop, name="browser-monitor", daemon=True)
        self._monitor.start()

    def stop_monitor(self) -> None:
        self._stop_monitor.set()
        if self._monitor and self._monitor.is_alive():
            self._monitor.join(timeout=2)

    def _monitor_loop(self) -> None:
        while not self._stop_monitor.wait(self._check_interval):
            with self._lock:
                process = self._process
                crashed = self._should_run and process is not None and process.poll() is not None
                if crashed:
                    self._record(
                        logging.WARNING,
                        "browser_crashed",
                        f"Browser crashed: name={self.browser_name} exit_code={process.returncode}",
                    )
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self._process = None
                    self._started_at = None
                    if self._auto_restart:
                        self._restart_count += 1
                        try:
                            self.start()
                        except RuntimeError as error:
                            self._record(logging.ERROR, "browser_restart_failed", str(error))