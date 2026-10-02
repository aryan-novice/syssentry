"""SQLite storage for metrics, check results and events."""

from __future__ import annotations

import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (ts REAL NOT NULL, name TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_metrics_name_ts ON metrics(name, ts);
CREATE TABLE IF NOT EXISTS checks (ts REAL NOT NULL, name TEXT NOT NULL, ok INTEGER NOT NULL, latency_ms REAL, detail TEXT);
CREATE INDEX IF NOT EXISTS idx_checks_name_ts ON checks(name, ts);
CREATE TABLE IF NOT EXISTS events (ts REAL NOT NULL, level TEXT NOT NULL, source TEXT NOT NULL, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def save_metrics(self, metrics: dict[str, float], ts: float | None = None) -> None:
        ts = ts or time.time()
        self.conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", [(ts, k, float(v)) for k, v in metrics.items()])
        self.conn.commit()

    def save_check(self, result, ts: float | None = None) -> None:
        self.conn.execute("INSERT INTO checks VALUES (?, ?, ?, ?, ?)",
                          (ts or time.time(), result.name, int(result.ok), result.latency_ms, result.detail))
        self.conn.commit()

    def save_event(self, event, ts: float | None = None) -> None:
        self.conn.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (ts or time.time(), event.level, event.source, event.message))
        self.conn.commit()

    def latest_metrics(self) -> dict[str, float]:
        row = self.conn.execute("SELECT MAX(ts) AS ts FROM metrics").fetchone()
        if not row or row["ts"] is None:
            return {}
        rows = self.conn.execute("SELECT name, value FROM metrics WHERE ts = ?", (row["ts"],))
        return {r["name"]: r["value"] for r in rows}

    def latest_checks(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT c.* FROM checks c JOIN (SELECT name, MAX(ts) AS ts FROM checks GROUP BY name) m "
            "ON c.name = m.name AND c.ts = m.ts ORDER BY c.name")
        return [dict(r) for r in rows]

    def series(self, name: str, since: float) -> list[tuple[float, float]]:
        rows = self.conn.execute("SELECT ts, value FROM metrics WHERE name = ? AND ts >= ? ORDER BY ts", (name, since))
        return [(r["ts"], r["value"]) for r in rows]

    def metric_summary(self, since: float) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, ROUND(AVG(value), 2) AS avg, ROUND(MAX(value), 2) AS max, COUNT(*) AS samples "
            "FROM metrics WHERE ts >= ? GROUP BY name ORDER BY name", (since,))
        return [dict(r) for r in rows]

    def availability(self, since: float) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, ROUND(100.0 * SUM(ok) / COUNT(*), 2) AS uptime_pct, COUNT(*) AS checks, "
            "ROUND(AVG(latency_ms), 1) AS avg_latency_ms FROM checks WHERE ts >= ? GROUP BY name ORDER BY name", (since,))
        return [dict(r) for r in rows]

    def events(self, since: float, limit: int = 100) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT ?", (since, limit))
        return [dict(r) for r in rows]

    def prune(self, retention_days: float) -> int:
        cutoff = time.time() - retention_days * 86400
        removed = 0
        for table in ("metrics", "checks", "events"):
            removed += self.conn.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,)).rowcount
        self.conn.commit()
        return removed
