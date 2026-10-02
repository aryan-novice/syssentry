"""Loads and validates the YAML configuration file."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULTS = {
    "hostname": None,
    "interval_seconds": 30,
    "database": "syssentry.db",
    "retention_days": 7,
    "thresholds": [
        {"metric": "cpu_percent", "warn": 80, "crit": 95, "for": 3},
        {"metric": "memory_percent", "warn": 80, "crit": 92, "for": 3},
        {"metric": "swap_percent", "warn": 50, "crit": 80, "for": 3},
        {"metric": "disk_percent:/", "warn": 80, "crit": 90, "for": 1},
        {"metric": "load_per_cpu", "warn": 1.5, "crit": 3.0, "for": 3},
    ],
    "services": [],
    "logs": [],
    "alerts": {"cooldown_seconds": 300, "channels": [{"type": "console"}]},
    "remediation": {"enabled": False, "dry_run": True, "max_attempts": 3},
    "web": {"host": "127.0.0.1", "port": 8085},
}

VALID_SERVICE_TYPES = {"systemd", "tcp", "http", "process"}


class ConfigError(ValueError):
    pass


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def validate(cfg: dict) -> dict:
    if cfg["interval_seconds"] <= 0:
        raise ConfigError("interval_seconds must be positive")
    for rule in cfg["thresholds"]:
        if "metric" not in rule:
            raise ConfigError(f"threshold rule without metric: {rule}")
        warn, crit = rule.get("warn"), rule.get("crit")
        if warn is not None and crit is not None and warn > crit:
            raise ConfigError(f"{rule['metric']}: warn ({warn}) is above crit ({crit})")
    names = set()
    for svc in cfg["services"]:
        if svc.get("type") not in VALID_SERVICE_TYPES:
            raise ConfigError(f"service {svc.get('name')!r} has unknown type {svc.get('type')!r}")
        if not svc.get("name"):
            raise ConfigError(f"service without a name: {svc}")
        if svc["name"] in names:
            raise ConfigError(f"duplicate service name {svc['name']!r}")
        names.add(svc["name"])
    return cfg


def load(path: str | Path | None) -> dict:
    data = {}
    if path:
        text = Path(path).read_text()
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ConfigError("config root must be a mapping")
    return validate(_merge(DEFAULTS, data))
