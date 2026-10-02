#!/usr/bin/env bash
# End-to-end demo: start a service, crash it, inject an SSH brute-force attack,
# and watch SysSentry alert, auto-restart the service and write a report.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -f demo/demo.db* demo/alerts.log demo/auth.log demo/report.md
touch demo/auth.log

bash demo/start_app.sh
python3 -m syssentry -c demo/config.demo.yaml run --cycles 12 &
AGENT=$!
sleep 3

echo ">>> simulating a crash of demo-api (kill -9)"
kill -9 "$(cat demo/demo_app.pid)"

echo ">>> simulating an SSH brute-force attack in demo/auth.log"
for i in $(seq 1 8); do
  echo "$(date '+%b %e %H:%M:%S') demo-host sshd[42${i}]: Failed password for invalid user admin from 203.0.113.50 port 4${i}22 ssh2" >> demo/auth.log
done

wait "$AGENT"
python3 -m syssentry -c demo/config.demo.yaml report --hours 1 -o demo/report.md
kill "$(cat demo/demo_app.pid)" 2>/dev/null || true
echo ">>> alerts written to demo/alerts.log, report to demo/report.md"
