"""The monitoring loop: collect -> evaluate -> alert -> remediate -> store."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field

from . import collectors
from .alerts import AlertManager, build_channels
from .checks import CheckResult, run_check
from .logscan import LogWatch
from .remediate import Remediator
from .rules import Event, RuleEngine, ServiceTracker
from .store import Store


@dataclass
class CycleResult:
    metrics: dict[str, float]
    checks: list[CheckResult]
    events: list[Event] = field(default_factory=list)
    duration_ms: float = 0.0


class Agent:
    def __init__(self, cfg: dict, store: Store | None = None, collect=collectors.collect, check=run_check):
        self.cfg = cfg
        self.hostname = cfg.get("hostname") or socket.gethostname()
        self.store = store if store is not None else Store(cfg["database"])
        self.collect, self.check = collect, check
        self.rules = RuleEngine(cfg["thresholds"])
        self.services = ServiceTracker()
        self.logs = [LogWatch(**lw) for lw in cfg["logs"]]
        alert_cfg = cfg["alerts"]
        self.alerts = AlertManager(build_channels(alert_cfg["channels"]), self.hostname, alert_cfg["cooldown_seconds"])
        rem = cfg["remediation"]
        self.remediator = Remediator(rem["enabled"], rem["dry_run"], rem["max_attempts"])
        self.down_since: dict[str, float] = {}

    def _emit(self, event: Event, events: list[Event]) -> None:
        events.append(event)
        self.store.save_event(event)
        self.alerts.dispatch(event)

    def run_once(self) -> CycleResult:
        start = time.perf_counter()
        events: list[Event] = []

        metrics = self.collect()
        self.store.save_metrics(metrics)
        for event in self.rules.evaluate(metrics):
            self._emit(event, events)

        results = []
        for svc in self.cfg["services"]:
            result = self.check(svc)
            results.append(result)
            self.store.save_check(result)
            event = self.services.update(svc["name"], result.ok, result.detail, svc.get("failures_before_alert"))
            if event and not event.resolved:
                self.down_since[svc["name"]] = time.time()
            if event and event.resolved:
                downtime = time.time() - self.down_since.pop(svc["name"], time.time())
                event.message += f" (down for {downtime:.0f}s)"
                event.value = round(downtime, 1)
                self.remediator.reset(svc["name"])
            if event:
                self._emit(event, events)
            if svc["name"] in self.services.down:
                self._remediate(svc, events)

        for watch in self.logs:
            for event in watch.scan():
                self._emit(event, events)

        duration = round((time.perf_counter() - start) * 1000, 1)
        return CycleResult(metrics, results, events, duration)

    def _remediate(self, svc: dict, events: list[Event]) -> None:
        outcome = self.remediator.attempt(svc)
        if outcome is None:
            return
        cmd = " ".join(outcome.command)
        if not outcome.executed and outcome.success:
            msg = f"[dry-run] would run `{cmd}` to fix {svc['name']}"
        elif outcome.executed:
            status = "succeeded" if outcome.success else "failed"
            msg = f"auto-remediation `{cmd}` {status} for {svc['name']}: {outcome.output}"
        else:
            msg = f"{svc['name']}: {outcome.output}"
        level = "warning" if outcome.success else "critical"
        self._emit(Event(level, f"remediation:{svc['name']}", msg), events)

    def run_forever(self, cycles: int | None = None) -> None:
        interval = self.cfg["interval_seconds"]
        done = 0
        last_prune = 0.0
        while cycles is None or done < cycles:
            started = time.monotonic()
            self.run_once()
            if time.time() - last_prune > 3600:
                self.store.prune(self.cfg["retention_days"])
                last_prune = time.time()
            done += 1
            if cycles is not None and done >= cycles:
                break
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
