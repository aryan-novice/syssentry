"""Small Flask dashboard and JSON API over the SQLite store."""

from __future__ import annotations

import time

from flask import Flask, jsonify, render_template_string, request

from .store import Store

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30"><title>SysSentry - {{ host }}</title>
<style>
 body{font-family:system-ui,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
 header{padding:16px 24px;background:#111827;border-bottom:1px solid #1f2937}
 main{padding:24px;display:grid;gap:20px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
 section{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:16px}
 h1{margin:0;font-size:20px} h2{margin:0 0 12px;font-size:15px;color:#94a3b8}
 table{width:100%;border-collapse:collapse;font-size:14px} td,th{padding:6px 4px;text-align:left;border-bottom:1px solid #1f2937}
 .ok{color:#4ade80}.warning{color:#facc15}.critical{color:#f87171}
 .bar{height:8px;background:#1f2937;border-radius:4px}.fill{height:8px;border-radius:4px}
</style></head><body>
<header><h1>SysSentry &middot; {{ host }}</h1><small>auto-refreshes every 30 s</small></header>
<main>
<section><h2>Resources</h2><table>
{% for name, value in metrics %}<tr><td>{{ name }}</td><td>{{ value }}</td>
<td style="width:40%">{% if 'percent' in name %}<div class="bar"><div class="fill" style="width:{{ value }}%;background:{{ '#f87171' if value>=90 else '#facc15' if value>=80 else '#4ade80' }}"></div></div>{% endif %}</td></tr>{% endfor %}
</table></section>
<section><h2>Services</h2><table><tr><th>Service</th><th>Status</th><th>Latency</th></tr>
{% for c in checks %}<tr><td>{{ c.name }}</td><td class="{{ 'ok' if c.ok else 'critical' }}">{{ 'UP' if c.ok else 'DOWN' }}</td><td>{{ c.latency_ms }} ms</td></tr>
{% else %}<tr><td colspan="3">No services configured</td></tr>{% endfor %}</table></section>
<section style="grid-column:1/-1"><h2>Recent events (24 h)</h2><table>
{% for e in events %}<tr><td>{{ e.when }}</td><td class="{{ e.level }}">{{ e.level|upper }}</td><td>{{ e.source }}</td><td>{{ e.message }}</td></tr>
{% else %}<tr><td>No events. All quiet.</td></tr>{% endfor %}</table></section>
</main></body></html>"""


def create_app(store: Store, hostname: str) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        metrics = sorted(store.latest_metrics().items())
        events = store.events(time.time() - 86400, limit=30)
        for e in events:
            e["when"] = time.strftime("%m-%d %H:%M:%S", time.localtime(e["ts"]))
        return render_template_string(PAGE, host=hostname, metrics=metrics, checks=store.latest_checks(), events=events)

    @app.get("/api/status")
    def status():
        checks = store.latest_checks()
        down = [c["name"] for c in checks if not c["ok"]]
        return jsonify(host=hostname, healthy=not down, down=down, metrics=store.latest_metrics(), checks=checks)

    @app.get("/api/metrics/<path:name>")
    def series(name):
        hours = float(request.args.get("hours", 1))
        points = store.series(name, time.time() - hours * 3600)
        return jsonify(name=name, points=[{"ts": ts, "value": v} for ts, v in points])

    @app.get("/api/events")
    def events():
        hours = float(request.args.get("hours", 24))
        return jsonify(store.events(time.time() - hours * 3600, limit=int(request.args.get("limit", 100))))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
