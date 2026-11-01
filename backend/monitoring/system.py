"""Collect host metrics directly from the operating system."""

from __future__ import annotations

import platform
import socket
import threading
import time
from pathlib import Path
from typing import Any

import psutil

_started_at = time.time()
_network_lock = threading.Lock()
_network_previous: tuple[float, int, int] | None = None


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith(("model name", "hardware")) and ":" in line:
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def _private_host_ip() -> str | None:
    """Return a local interface address without querying an external service."""
    try:
        for addresses in psutil.net_if_addrs().values():
            for address in addresses:
                if address.family == socket.AF_INET and not address.address.startswith("127."):
                    return address.address
    except (OSError, psutil.Error):
        pass
    return None


def _network_rates() -> dict[str, int]:
    global _network_previous
    counters = psutil.net_io_counters()
    if counters is None:
        return {"bytes_sent_per_second": 0, "bytes_received_per_second": 0}
    now = time.monotonic()
    with _network_lock:
        previous = _network_previous
        _network_previous = (now, counters.bytes_sent, counters.bytes_recv)
    if previous is None:
        return {"bytes_sent_per_second": 0, "bytes_received_per_second": 0}
    elapsed = max(now - previous[0], 0.001)
    return {
        "bytes_sent_per_second": max(0, int((counters.bytes_sent - previous[1]) / elapsed)),
        "bytes_received_per_second": max(0, int((counters.bytes_recv - previous[2]) / elapsed)),
    }


def _cpu_temperature() -> float | None:
    try:
        sensors = psutil.sensors_temperatures()
        for entries in sensors.values():
            for entry in entries:
                if entry.current is not None:
                    return float(entry.current)
    except (AttributeError, OSError, psutil.Error):
        pass
    return None


def _oom_kill_count() -> int | None:
    try:
        for line in Path("/proc/vmstat").read_text().splitlines():
            if line.startswith("oom_kill "):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def _zombie_process_count() -> int | None:
    count = 0
    try:
        for process in psutil.process_iter(attrs=["status"]):
            try:
                if process.info["status"] == psutil.STATUS_ZOMBIE:
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except psutil.Error:
        return None
    return count


def collect_system_metrics() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    boot_time = psutil.boot_time()
    cpu_frequency = psutil.cpu_freq()
    return {
        "cpu": {
            "model": _cpu_model(),
            "cores_logical": psutil.cpu_count(logical=True) or 1,
            "cores_physical": psutil.cpu_count(logical=False),
            "usage_percent": psutil.cpu_percent(interval=None),
            "frequency_mhz": cpu_frequency.current if cpu_frequency else None,
            "temperature_c": _cpu_temperature(),
        },
        "memory": {
            "total_bytes": memory.total,
            "used_bytes": memory.used,
            "available_bytes": memory.available,
            "usage_percent": memory.percent,
        },
        "swap": {
            "total_bytes": swap.total,
            "used_bytes": swap.used,
            "usage_percent": swap.percent,
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "usage_percent": disk.percent,
        },
        "host": {
            "uptime_seconds": max(0, int(time.time() - boot_time)),
            "os": platform.platform(),
            "kernel": platform.release(),
            "local_ip": _private_host_ip(),
            "oom_kill_count": _oom_kill_count(),
        },
        "network": _network_rates(),
        "processes": {"zombie_count": _zombie_process_count()},
        "backend": {"uptime_seconds": max(0, int(time.time() - _started_at))},
        "sampled_at": int(time.time()),
    }