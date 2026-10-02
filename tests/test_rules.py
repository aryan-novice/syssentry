from syssentry.rules import RuleEngine, ServiceTracker, classify

RULE = [{"metric": "cpu_percent", "warn": 80, "crit": 95, "for": 3}]


def test_classify_boundaries():
    assert classify(79.9, 80, 95) == "ok"
    assert classify(80, 80, 95) == "warning"
    assert classify(95, 80, 95) == "critical"


def test_single_spike_does_not_alert():
    engine = RuleEngine(RULE)
    assert engine.evaluate({"cpu_percent": 90}) == []
    assert engine.evaluate({"cpu_percent": 40}) == []
    assert engine.evaluate({"cpu_percent": 90}) == []


def test_sustained_breach_alerts_once_then_resolves():
    engine = RuleEngine(RULE)
    events = [e for v in (85, 86, 87, 88, 89) for e in engine.evaluate({"cpu_percent": v})]
    assert [e.level for e in events] == ["warning"]
    resolved = [e for v in (30, 30, 30) for e in engine.evaluate({"cpu_percent": v})]
    assert len(resolved) == 1 and resolved[0].resolved and resolved[0].level == "ok"


def test_warning_escalates_to_critical_immediately():
    engine = RuleEngine(RULE)
    for v in (85, 85, 85):
        engine.evaluate({"cpu_percent": v})
    events = engine.evaluate({"cpu_percent": 99})
    assert [e.level for e in events] == ["critical"]


def test_missing_metric_is_skipped():
    assert RuleEngine(RULE).evaluate({"memory_percent": 99}) == []


def test_service_tracker_needs_consecutive_failures():
    tracker = ServiceTracker(failures_before_alert=2)
    assert tracker.update("nginx", False, "refused") is None
    down = tracker.update("nginx", False, "refused")
    assert down.level == "critical" and "DOWN" in down.message
    assert tracker.update("nginx", False, "refused") is None  # no repeat while still down
    up = tracker.update("nginx", True, "ok")
    assert up.resolved and "RECOVERED" in up.message


def test_service_tracker_recovers_counter_on_success():
    tracker = ServiceTracker(failures_before_alert=2)
    tracker.update("db", False, "x")
    tracker.update("db", True, "ok")
    assert tracker.update("db", False, "x") is None
