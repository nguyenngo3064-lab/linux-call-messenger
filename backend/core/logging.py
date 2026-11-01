from __future__ import annotations

import logging
import os
import threading
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_logger = logging.getLogger("mck")
_handler: RotatingFileHandler | None = None
_handler_path: Path | None = None
_lock = threading.Lock()


def configure_file_logging(directory: str | Path | None, size_mb: int) -> None:
    global _handler, _handler_path
    log_dir = Path(directory or os.getenv("MCK_LOG_DIR", "logs"))
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_dir.chmod(0o700)
    log_path = log_dir / "keeper.log"
    with _lock:
        if _handler is None or _handler_path != log_path:
            if _handler is not None:
                _logger.removeHandler(_handler)
                _handler.close()
            _handler = RotatingFileHandler(
                log_path,
                maxBytes=max(1, size_mb) * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
            _handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            _logger.addHandler(_handler)
            _logger.setLevel(logging.INFO)
            _logger.propagate = False
            _handler_path = log_path
        else:
            _handler.maxBytes = max(1, size_mb) * 1024 * 1024
        os.chmod(log_path, 0o600)


def read_recent_file_logs(limit: int = 100) -> list[dict[str, str | int]]:
    bounded_limit = max(1, min(int(limit), 500))
    log_dir = _handler_path.parent if _handler_path else Path(os.getenv("MCK_LOG_DIR", "logs"))
    lines: deque[str] = deque(maxlen=bounded_limit)
    for path in (log_dir / "keeper.log.2", log_dir / "keeper.log.1", log_dir / "keeper.log"):
        try:
            with path.open(encoding="utf-8", errors="replace") as log_file:
                lines.extend(log_file)
        except FileNotFoundError:
            continue
    entries: list[dict[str, str | int]] = []
    for line in lines:
        parts = line.rstrip("\r\n").split(maxsplit=3)
        if len(parts) != 4:
            continue
        try:
            timestamp = datetime.strptime(
                f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S,%f"
            ).timestamp()
        except ValueError:
            continue
        entries.append(
            {
                "created_at": int(timestamp),
                "level": parts[2],
                "event_type": parts[3].split(" ", 1)[0],
                "message": parts[3].partition(" ")[2],
            }
        )
    return entries


def clear_file_logs() -> int:
    if _handler is None or _handler_path is None:
        return 0
    removed_lines = 0
    with _lock:
        _handler.acquire()
        try:
            _handler.flush()
            if _handler.stream:
                with _handler_path.open(encoding="utf-8", errors="replace") as log_file:
                    removed_lines += sum(1 for _ in log_file)
                _handler.stream.seek(0)
                _handler.stream.truncate()
                _handler.stream.flush()
            for suffix in (".1", ".2"):
                backup = Path(f"{_handler_path}{suffix}")
                if backup.exists():
                    with backup.open(encoding="utf-8", errors="replace") as log_file:
                        removed_lines += sum(1 for _ in log_file)
                    backup.unlink()
        finally:
            _handler.release()
    return removed_lines