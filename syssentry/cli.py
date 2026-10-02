"""Command line interface.

    syssentry check      one-shot check, Nagios-style exit code (0 OK, 1 WARNING, 2 CRITICAL)
    syssentry run        continuous monitoring loop
    syssentry report     Markdown health / shift-handover report
    syssentry web        dashboard + JSON API
    syssentry inventory  host facts for asset tracking
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading

from . import __version__, collectors, config
from .checks import run_check
from .rules import classify

EXIT = {"ok": 0, "warning": 1, "critical": 2}


def cmd_check(cfg: dict, args) -> int:
    metrics = collectors.collect()
    worst = "ok"
    rows = []
    for rule in cfg["thresholds"]:
        if rule["metric"] not in metrics:
            continue
        value = metrics[rule["metric"]]
        level = classify(value, rule.get("warn"), rule.get("crit"))
        rows.append((rule["metric"], value, level))
        if EXIT[level] > EXIT[worst]:
            worst = level
    for svc in cfg["services"]:
        res = run_check(svc)
        level = "ok" if res.ok else "critical"
        rows.append((f"service:{res.name}", f"{res.latency_ms} ms", level))
        if not res.ok:
            worst = "critical"
    if args.json:
        print(json.dumps({"status": worst, "results": [{"name": n, "value": v, "level": lv} for n, v, lv in rows]}, indent=2))
    else:
        width = max((len(r[0]) for r in rows), default=10)
        for name, value, level in rows:
            print(f"{name:<{width}}  {str(value):>10}  {level.upper()}")
        print(f"\nOVERALL: {worst.upper()}")
    return EXIT[worst]


def cmd_run(cfg: dict, args) -> int:
    from .agent import Agent

    agent = Agent(cfg)
    if args.with_web:
        from .web import create_app

        app = create_app(agent.store, agent.hostname)
        threading.Thread(target=app.run, kwargs={"host": cfg["web"]["host"], "port": cfg["web"]["port"]}, daemon=True).start()
    print(f"SysSentry {__version__} monitoring {agent.hostname} every {cfg['interval_seconds']}s "
          f"({len(cfg['services'])} services, {len(cfg['logs'])} logs)", flush=True)
    try:
        agent.run_forever(cycles=args.cycles)
    except KeyboardInterrupt:
        print("stopped")
    return 0


def cmd_report(cfg: dict, args) -> int:
    from .report import build_report
    from .store import Store

    text = build_report(Store(cfg["database"]), args.hours, cfg.get("hostname"))
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(text)
        print(f"report written to {args.output}")
    else:
        print(text)
    return 0


def cmd_web(cfg: dict, args) -> int:
    from .store import Store
    from .web import create_app

    app = create_app(Store(cfg["database"]), cfg.get("hostname") or socket.gethostname())
    app.run(host=cfg["web"]["host"], port=cfg["web"]["port"])
    return 0


def cmd_inventory(cfg: dict, args) -> int:
    print(json.dumps(collectors.inventory(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="syssentry", description="Linux server health monitor with auto-remediation")
    parser.add_argument("-c", "--config", help="path to YAML config (defaults are used if omitted)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="one-shot health check with Nagios exit codes")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("run", help="continuous monitoring loop")
    p.add_argument("--cycles", type=int, help="stop after N cycles (default: run forever)")
    p.add_argument("--with-web", action="store_true", help="also serve the dashboard")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("report", help="Markdown health report")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_report)
    sub.add_parser("web", help="serve dashboard and JSON API").set_defaults(func=cmd_web)
    sub.add_parser("inventory", help="print host inventory as JSON").set_defaults(func=cmd_inventory)

    args = parser.parse_args(argv)
    try:
        cfg = config.load(args.config)
    except (OSError, config.ConfigError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 3
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
