"""Service health checks: systemd units, TCP ports, HTTP endpoints and processes."""

from __future__ import annotations

import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import psutil


@dataclass
class CheckResult:
    name: str
    ok: bool
    latency_ms: float
    detail: str


def check_systemd(unit: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        return False, "systemctl not available on this host"
    except subprocess.TimeoutExpired:
        return False, "systemctl timed out"
    state = proc.stdout.strip() or proc.stderr.strip()
    return state == "active", f"unit {unit} is {state}"


def check_tcp(host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} accepting connections"
    except OSError as exc:
        return False, f"{host}:{port} unreachable ({exc.strerror or exc})"


def check_http(url: str, timeout: float, expect_status: int = 200, expect_text: str | None = None) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "SysSentry/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, ""
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"{url} unreachable ({reason})"
    if status != expect_status:
        return False, f"{url} returned HTTP {status}, expected {expect_status}"
    if expect_text and expect_text not in body:
        return False, f"{url} response missing {expect_text!r}"
    return True, f"{url} returned HTTP {status}"


def check_process(pattern: str) -> tuple[bool, str]:
    for proc in psutil.process_iter(["name", "cmdline"]):
        cmdline = " ".join(proc.info["cmdline"] or [])
        if pattern == proc.info["name"] or pattern in cmdline:
            return True, f"process matching {pattern!r} running (pid {proc.pid})"
    return False, f"no process matching {pattern!r}"


def run_check(svc: dict) -> CheckResult:
    kind = svc["type"]
    timeout = float(svc.get("timeout", 3))
    start = time.perf_counter()
    if kind == "systemd":
        ok, detail = check_systemd(svc.get("unit", svc["name"]))
    elif kind == "tcp":
        ok, detail = check_tcp(svc.get("host", "127.0.0.1"), int(svc["port"]), timeout)
    elif kind == "http":
        ok, detail = check_http(svc["url"], timeout, int(svc.get("expect_status", 200)), svc.get("expect_text"))
    elif kind == "process":
        ok, detail = check_process(svc["pattern"])
    else:
        raise ValueError(f"unknown check type {kind}")
    latency = round((time.perf_counter() - start) * 1000, 1)
    return CheckResult(svc["name"], ok, latency, detail)
