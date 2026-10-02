"""Collects host metrics (CPU, memory, disk, load, network, processes) with psutil."""

from __future__ import annotations

import os
import platform
import socket
import time

import psutil

# Pseudo filesystems that should never trigger disk alerts.
IGNORED_FSTYPES = {"tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "nsfs", "cgroup2"}

_last_net = None


def disk_usage() -> dict[str, float]:
    usage = {}
    for part in psutil.disk_partitions(all=False):
        if part.fstype in IGNORED_FSTYPES or part.mountpoint.startswith("/snap"):
            continue
        try:
            usage[part.mountpoint] = psutil.disk_usage(part.mountpoint).percent
        except (PermissionError, OSError):
            continue
    if "/" not in usage:
        usage["/"] = psutil.disk_usage("/").percent
    return usage


def network_rates() -> dict[str, float]:
    """Bytes/sec sent and received since the previous call (0 on the first call)."""
    global _last_net
    now = time.monotonic()
    counters = psutil.net_io_counters()
    rates = {"net_sent_bps": 0.0, "net_recv_bps": 0.0}
    if _last_net is not None:
        prev_t, prev = _last_net
        dt = max(now - prev_t, 1e-6)
        rates["net_sent_bps"] = round((counters.bytes_sent - prev.bytes_sent) / dt, 1)
        rates["net_recv_bps"] = round((counters.bytes_recv - prev.bytes_recv) / dt, 1)
    _last_net = (now, counters)
    return rates


def top_processes(limit: int = 5) -> list[dict]:
    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "memory_percent", "cpu_percent"]):
        info = p.info
        procs.append({
            "pid": info["pid"],
            "name": info["name"],
            "user": info["username"],
            "memory_percent": round(info["memory_percent"] or 0.0, 2),
            "cpu_percent": info["cpu_percent"] or 0.0,
        })
    procs.sort(key=lambda p: p["memory_percent"], reverse=True)
    return procs[:limit]


def collect() -> dict[str, float]:
    """Return a flat {metric_name: value} snapshot of the host."""
    metrics: dict[str, float] = {}
    metrics["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    vm = psutil.virtual_memory()
    metrics["memory_percent"] = vm.percent
    metrics["memory_available_mb"] = round(vm.available / 2**20, 1)
    metrics["swap_percent"] = psutil.swap_memory().percent
    load1, load5, load15 = os.getloadavg()
    cpus = psutil.cpu_count() or 1
    metrics["load_1m"] = round(load1, 2)
    metrics["load_per_cpu"] = round(load1 / cpus, 2)
    for mount, pct in disk_usage().items():
        metrics[f"disk_percent:{mount}"] = pct
    metrics.update(network_rates())
    metrics["process_count"] = len(psutil.pids())
    metrics["uptime_hours"] = round((time.time() - psutil.boot_time()) / 3600, 2)
    return metrics


def inventory() -> dict:
    """Static facts about the host, useful for asset tracking and tickets."""
    vm = psutil.virtual_memory()
    addrs = {}
    for iface, entries in psutil.net_if_addrs().items():
        ipv4 = [e.address for e in entries if e.family == socket.AF_INET]
        if ipv4:
            addrs[iface] = ipv4
    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "distro": _distro_name(),
        "python": platform.python_version(),
        "cpu_cores": psutil.cpu_count(logical=False) or psutil.cpu_count(),
        "cpu_threads": psutil.cpu_count(),
        "memory_gb": round(vm.total / 2**30, 2),
        "disks": {m: f"{p}% used" for m, p in disk_usage().items()},
        "ipv4": addrs,
        "boot_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(psutil.boot_time())),
    }


def _distro_name() -> str:
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"
