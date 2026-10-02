import sys

import pytest

from syssentry.alerts import AlertManager, FileChannel, build_channels
from syssentry.remediate import Remediator
from syssentry.rules import Event


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, text, event):
        self.sent.append(text)


class Broken:
    def send(self, text, event):
        raise ConnectionError("webhook down")


def test_cooldown_suppresses_repeats_but_not_resolutions():
    clock = [0.0]
    rec = Recorder()
    mgr = AlertManager([rec], "web-01", cooldown_seconds=300, clock=lambda: clock[0])
    assert mgr.dispatch(Event("critical", "nginx", "nginx DOWN"))
    clock[0] = 100
    assert not mgr.dispatch(Event("critical", "nginx", "nginx DOWN"))
    assert mgr.dispatch(Event("ok", "nginx", "nginx RECOVERED", resolved=True))
    clock[0] = 301
    assert mgr.dispatch(Event("critical", "nginx", "nginx DOWN"))
    assert len(rec.sent) == 3 and mgr.suppressed == 1
    assert "[CRITICAL] web-01: nginx DOWN" in rec.sent[0]


def test_broken_channel_does_not_block_others():
    rec = Recorder()
    mgr = AlertManager([Broken(), rec], "h", cooldown_seconds=0)
    mgr.dispatch(Event("warning", "disk", "disk 85%"))
    assert len(rec.sent) == 1 and mgr.failures == 1


def test_file_channel(tmp_path):
    path = tmp_path / "alerts.log"
    FileChannel(str(path)).send("hello", Event("warning", "x", "y"))
    assert path.read_text() == "hello\n"


def test_unknown_channel_rejected():
    with pytest.raises(ValueError):
        build_channels([{"type": "pager"}])


def test_remediation_disabled_by_default():
    assert Remediator().attempt({"name": "nginx", "remediation": "restart"}) is None


def test_dry_run_and_attempt_limit():
    rem = Remediator(enabled=True, dry_run=True, max_attempts=2)
    svc = {"name": "nginx", "unit": "nginx.service", "remediation": "restart"}
    first = rem.attempt(svc)
    assert first.command == ["systemctl", "restart", "nginx.service"] and not first.executed
    rem.attempt(svc)
    third = rem.attempt(svc)
    assert not third.success and "gave up" in third.output
    rem.reset("nginx")
    assert rem.attempt(svc).success


def test_custom_command_runs():
    rem = Remediator(enabled=True, dry_run=False)
    svc = {"name": "app", "remediation": {"command": [sys.executable, "-c", "print('restarted')"]}}
    result = rem.attempt(svc)
    assert result.executed and result.success and result.output == "restarted"


def test_failing_command_reported():
    rem = Remediator(enabled=True, dry_run=False)
    result = rem.attempt({"name": "app", "remediation": {"command": "false"}})
    assert result.executed and not result.success
