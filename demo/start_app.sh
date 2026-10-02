#!/usr/bin/env bash
# Runbook used by the demo's auto-remediation: (re)start the demo service in the background.
set -euo pipefail
cd "$(dirname "$0")"
nohup python3 demo_app.py 8099 >/dev/null 2>&1 &
sleep 0.5
echo "demo_app started (pid $(cat demo_app.pid))"
