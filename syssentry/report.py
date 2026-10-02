"""Builds a Markdown shift-handover / daily health report from stored data."""

from __future__ import annotations

import socket
import time
from datetime import datetime

from .store import Store

LABELS = {"ok": "RESOLVED", "warning": "WARNING", "critical": "CRITICAL"}


def build_report(store: Store, hours: float = 24, hostname: str | None = None) -> str:
    since = time.time() - hours * 3600
    host = hostname or socket.gethostname()
    lines = [
        f"# Health report: {host}",
        "",
        f"Window: last {hours:g} h (generated {datetime.now():%Y-%m-%d %H:%M})",
        "",
    ]

    events = store.events(since, limit=1000)
    crit = sum(1 for e in events if e["level"] == "critical")
    warn = sum(1 for e in events if e["level"] == "warning")
    resolved = sum(1 for e in events if e["level"] == "ok")
    verdict = "ATTENTION NEEDED" if crit else ("STABLE WITH WARNINGS" if warn else "ALL CLEAR")
    lines += [f"**Status: {verdict}** - {crit} critical, {warn} warning, {resolved} resolved events", ""]

    avail = store.availability(since)
    if avail:
        lines += ["## Service availability", "", "| Service | Uptime % | Checks | Avg latency (ms) |", "|---|---|---|---|"]
        lines += [f"| {a['name']} | {a['uptime_pct']} | {a['checks']} | {a['avg_latency_ms']} |" for a in avail]
        lines.append("")

    summary = store.metric_summary(since)
    if summary:
        lines += ["## Resource usage", "", "| Metric | Average | Peak | Samples |", "|---|---|---|---|"]
        lines += [f"| {m['name']} | {m['avg']} | {m['max']} | {m['samples']} |" for m in summary]
        lines.append("")

    if events:
        lines += ["## Event timeline (newest first)", ""]
        for e in events[:25]:
            stamp = datetime.fromtimestamp(e["ts"]).strftime("%m-%d %H:%M:%S")
            lines.append(f"- `{stamp}` **{LABELS[e['level']]}** {e['source']}: {e['message']}")
        lines.append("")
    else:
        lines += ["No incidents recorded in this window.", ""]
    return "\n".join(lines)
