#!/usr/bin/env bash
# triage.sh - first-response snapshot for an on-call engineer.
# Gathers the facts usually asked for in the first five minutes of an incident
# and saves them to a timestamped file you can attach to the ticket.
#
#   sudo ./scripts/triage.sh            # print and save to ./triage-<host>-<time>.txt
#   ./scripts/triage.sh -o /tmp/out.txt
set -uo pipefail

OUT="triage-$(hostname)-$(date +%Y%m%d-%H%M%S).txt"
while getopts "o:h" opt; do
  case $opt in
    o) OUT=$OPTARG ;;
    h) sed -n '2,8p' "$0"; exit 0 ;;
    *) exit 1 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }
section() { printf '\n===== %s =====\n' "$1"; }

{
  section "HOST"
  echo "host: $(hostname)   time: $(date '+%F %T %Z')"
  grep -m1 PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"'
  echo "kernel: $(uname -r)"
  uptime

  section "CPU / MEMORY"
  echo "cpus: $(nproc)"
  free -h
  section "TOP 5 PROCESSES BY CPU"
  ps -eo pid,user,%cpu,%mem,etime,comm --sort=-%cpu | head -6
  section "TOP 5 PROCESSES BY MEMORY"
  ps -eo pid,user,%cpu,%mem,etime,comm --sort=-%mem | head -6

  section "DISK"
  df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null || df -h
  echo
  echo "inode usage above 80%:"
  df -i 2>/dev/null | awk 'NR>1 && $5+0 > 80 {print "  " $0}'
  echo "disks above 85% full:"
  df -P 2>/dev/null | awk 'NR>1 && $5+0 > 85 {print "  " $6 " at " $5}'

  section "NETWORK"
  if have ip; then ip -brief addr; fi
  echo
  echo "listening ports:"
  if have ss; then ss -tulpn 2>/dev/null | head -25; elif have netstat; then netstat -tulpn 2>/dev/null | head -25; fi
  echo
  echo "default route: $(ip route 2>/dev/null | awk '/default/ {print $3; exit}')"
  if have getent; then getent hosts google.com >/dev/null && echo "DNS: ok" || echo "DNS: FAILED"; fi

  section "SERVICES"
  if have systemctl && [ -d /run/systemd/system ]; then
    echo "system state: $(systemctl is-system-running 2>/dev/null)"
    systemctl --failed --no-legend 2>/dev/null || true
  else
    echo "systemd not available"
  fi

  section "RECENT ERRORS (last 30 min)"
  if have journalctl; then
    journalctl -p err --since "30 min ago" --no-pager 2>/dev/null | tail -20
  elif [ -r /var/log/syslog ]; then
    grep -iE "error|fail|critical" /var/log/syslog | tail -20
  else
    echo "no readable system log"
  fi

  section "SSH FAILED LOGINS (top sources)"
  for f in /var/log/auth.log /var/log/secure; do
    [ -r "$f" ] && grep -hoE "Failed password .* from [0-9.]+" "$f" | awk '{print $NF}' | sort | uniq -c | sort -rn | head -5
  done
  echo "(end)"
} 2>&1 | tee "$OUT"

echo
echo "saved to $OUT"
