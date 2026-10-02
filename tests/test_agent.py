import time

from syssentry import cli, config
from syssentry.agent import Agent
from syssentry.checks import CheckResult
from syssentry.report import build_report
from syssentry.store import Store
from syssentry.web import create_app


def make_agent(tmp_path, metrics, service_ok, remediation=None):
    cfg = config.load(None)
    cfg["database"] = str(tmp_path / "s.db")
    cfg["alerts"]["channels"] = [{"type": "file", "path": str(tmp_path / "alerts.log")}]
    cfg["services"] = [{"name": "api", "type": "tcp", "port": 1, "remediation": {"command": "true"}}]
    cfg["remediation"] = remediation or {"enabled": True, "dry_run": False, "max_attempts": 3}
    cfg["thresholds"] = [{"metric": "disk_percent:/", "warn": 80, "crit": 90, "for": 1}]
    state = iter(service_ok)
    agent = Agent(cfg, collect=lambda: dict(metrics), check=lambda svc: CheckResult(svc["name"], next(state), 1.0, "probe"))
    return agent


def test_outage_remediation_and_recovery(tmp_path):
    agent = make_agent(tmp_path, {"disk_percent:/": 50}, [False, False, False, True])
    levels = []
    for _ in range(4):
        levels.append([(e.source, e.level) for e in agent.run_once().events])
    assert levels[0] == []                                  # first failure tolerated
    assert ("api", "critical") in levels[1]                 # DOWN after 2 failures
    assert ("remediation:api", "warning") in levels[1]      # restart attempted
    assert ("remediation:api", "warning") in levels[2]      # retried while still down
    assert levels[3] == [("api", "ok")]                     # RECOVERED
    assert agent.remediator.attempts == {}
    log = (tmp_path / "alerts.log").read_text()
    assert "api DOWN" in log and "RECOVERED" in log and "down for" in log


def test_metric_alert_stored_and_reported(tmp_path):
    agent = make_agent(tmp_path, {"disk_percent:/": 93}, [True])
    result = agent.run_once()
    assert [e.level for e in result.events] == ["critical"]
    report = build_report(agent.store, hours=1, hostname="web-01")
    assert "ATTENTION NEEDED" in report and "| api | 100.0 | 1 |" in report


def test_web_api(tmp_path):
    agent = make_agent(tmp_path, {"disk_percent:/": 40, "cpu_percent": 12}, [False])
    agent.run_once()
    client = create_app(agent.store, "web-01").test_client()
    status = client.get("/api/status").get_json()
    assert status["healthy"] is False and status["down"] == ["api"]
    assert client.get("/api/metrics/cpu_percent?hours=1").get_json()["points"][0]["value"] == 12
    assert b"SysSentry" in client.get("/").data
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_store_prune(tmp_path):
    store = Store(str(tmp_path / "p.db"))
    store.save_metrics({"cpu_percent": 1}, ts=time.time() - 10 * 86400)
    store.save_metrics({"cpu_percent": 2})
    assert store.prune(7) == 1
    assert store.latest_metrics() == {"cpu_percent": 2}


def test_cli_check_exit_code_and_bad_config(tmp_path, capsys):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("thresholds:\n  - {metric: memory_percent, warn: 0, crit: 0.001}\n")
    assert cli.main(["-c", str(cfg), "check"]) == 2
    assert "OVERALL: CRITICAL" in capsys.readouterr().out
    bad = tmp_path / "bad.yaml"
    bad.write_text("interval_seconds: -1")
    assert cli.main(["-c", str(bad), "check"]) == 3
