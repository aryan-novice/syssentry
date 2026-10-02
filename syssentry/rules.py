"""Threshold rules with flap protection.

A metric only changes state after it has breached (or recovered) for `for`
consecutive samples, so a single CPU spike does not page anyone at 3 AM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LEVELS = {"ok": 0, "warning": 1, "critical": 2}


@dataclass
class Event:
    level: str  # ok | warning | critical
    source: str
    message: str
    value: float | None = None
    resolved: bool = False


@dataclass
class _State:
    level: str = "ok"
    pending: str | None = None
    count: int = 0


def classify(value: float, warn: float | None, crit: float | None) -> str:
    if crit is not None and value >= crit:
        return "critical"
    if warn is not None and value >= warn:
        return "warning"
    return "ok"


@dataclass
class RuleEngine:
    rules: list[dict]
    states: dict[str, _State] = field(default_factory=dict)

    def evaluate(self, metrics: dict[str, float]) -> list[Event]:
        events = []
        for rule in self.rules:
            name = rule["metric"]
            if name not in metrics:
                continue
            value = metrics[name]
            observed = classify(value, rule.get("warn"), rule.get("crit"))
            state = self.states.setdefault(name, _State())
            need = max(int(rule.get("for", 1)), 1)

            if observed == state.level:
                state.pending, state.count = None, 0
                continue
            if observed == state.pending:
                state.count += 1
            else:
                state.pending, state.count = observed, 1
            # Escalating straight to critical skips the wait: it is never a flap worth hiding.
            if state.count >= need or (observed == "critical" and LEVELS[state.level] == 1):
                previous = state.level
                state.level, state.pending, state.count = observed, None, 0
                events.append(self._event(name, rule, value, previous, observed))
        return events

    @staticmethod
    def _event(name: str, rule: dict, value: float, previous: str, new: str) -> Event:
        if new == "ok":
            return Event("ok", name, f"{name} back to normal at {value} (was {previous})", value, resolved=True)
        limit = rule.get("crit") if new == "critical" else rule.get("warn")
        return Event(new, name, f"{name} is {value}, above {new} threshold {limit}", value)


@dataclass
class ServiceTracker:
    """Turns raw pass/fail checks into DOWN / RECOVERED events."""

    failures_before_alert: int = 2
    fail_counts: dict[str, int] = field(default_factory=dict)
    down: set[str] = field(default_factory=set)

    def update(self, name: str, ok: bool, detail: str, needed: int | None = None) -> Event | None:
        needed = needed or self.failures_before_alert
        if ok:
            self.fail_counts[name] = 0
            if name in self.down:
                self.down.discard(name)
                return Event("ok", name, f"{name} RECOVERED: {detail}", resolved=True)
            return None
        self.fail_counts[name] = self.fail_counts.get(name, 0) + 1
        if self.fail_counts[name] >= needed and name not in self.down:
            self.down.add(name)
            return Event("critical", name, f"{name} DOWN: {detail}")
        return None
