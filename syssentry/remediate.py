"""Runbook-driven auto-remediation.

Only commands written in the config are ever run, each service gets a limited
number of attempts until it recovers, and dry-run mode (the default) logs what
would have happened without touching the system.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field

BUILTIN_ACTIONS = {
    "restart": lambda svc: ["systemctl", "restart", svc.get("unit", svc["name"])],
}


@dataclass
class RemediationResult:
    service: str
    command: list[str]
    executed: bool
    success: bool
    output: str


@dataclass
class Remediator:
    enabled: bool = False
    dry_run: bool = True
    max_attempts: int = 3
    attempts: dict[str, int] = field(default_factory=dict)

    def command_for(self, svc: dict) -> list[str] | None:
        action = svc.get("remediation")
        if not action:
            return None
        if isinstance(action, str) and action in BUILTIN_ACTIONS:
            return BUILTIN_ACTIONS[action](svc)
        if isinstance(action, dict) and "command" in action:
            cmd = action["command"]
            return shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        raise ValueError(f"service {svc['name']}: unsupported remediation {action!r}")

    def reset(self, name: str) -> None:
        self.attempts.pop(name, None)

    def attempt(self, svc: dict) -> RemediationResult | None:
        cmd = self.command_for(svc)
        if not self.enabled or cmd is None:
            return None
        name = svc["name"]
        used = self.attempts.get(name, 0)
        if used >= self.max_attempts:
            return RemediationResult(name, cmd, False, False, f"gave up after {used} attempts; escalate to a human")
        self.attempts[name] = used + 1
        if self.dry_run:
            return RemediationResult(name, cmd, False, True, "dry run: command not executed")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RemediationResult(name, cmd, True, False, str(exc))
        output = (proc.stdout + proc.stderr).strip()[-500:]
        return RemediationResult(name, cmd, True, proc.returncode == 0, output or f"exit code {proc.returncode}")
