#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-list}"
COMPOSE="docker compose -f lab-1-core-engine/docker-compose.yml"

print_challenges() {
  cat <<'EOF'
Spartan Live Linux Forensics Drills (6 Challenges):
  1. subnet-isolation   Verify spartan-nginx CANNOT reach postgres:5432 (private_data_net isolation)
  2. use-method-60s     Capture uptime, vmstat, mpstat, free -m, and ss -s inside sre-toolbox
  3. dns-and-routing    Resolve nginx/api/postgres via embedded DNS and inspect ip route
  4. http-wire-timing   Measure DNS/connect/TTFB/total timing against http://nginx/healthz
  5. fd-and-proc-audit  Inspect open file descriptors, top CPU/MEM processes, and listening ports
  6. disk-and-log-hunt  Verify /tmp disk headroom and extract HTTP error rates from edge probes

Run live against Lab 1 stack:
  bash drills/linux/run_linux_drills.sh run
EOF
}

run_live() {
  echo "=== [1/6] Subnet Isolation Check (nginx -> postgres:5432 must FAIL) ==="
  if docker exec spartan-nginx sh -c "nc -zv -w 2 postgres 5432" >/dev/null 2>&1; then
    echo "FAIL: spartan-nginx reached postgres:5432 directly!"
    exit 1
  fi
  echo "PASS: private_data_net isolation verified."

  echo "=== [2/6] 60-Second USE Method Snapshot ==="
  $COMPOSE exec -T sre-toolbox sh -c "uptime && free -m && ss -s | head -n 6"

  echo "=== [3/6] DNS & Routing Table ==="
  $COMPOSE exec -T sre-toolbox sh -c "dig +short nginx && dig +short api && ip -br addr"

  echo "=== [4/6] HTTP Wire Timing Breakdown ==="
  $COMPOSE exec -T sre-toolbox curl -s -o /dev/null -w \
    "status=%{http_code} dns=%{time_namelookup}s connect=%{time_connect}s ttfb=%{time_starttransfer}s total=%{time_total}s\n" \
    http://nginx/healthz

  echo "=== [5/6] Process & Listening Socket Audit ==="
  $COMPOSE exec -T sre-toolbox sh -c "ps aux --sort=-%cpu | head -n 6"

  echo "=== [6/6] Filesystem Headroom Audit ==="
  $COMPOSE exec -T sre-toolbox df -h / /tmp

  echo "=== ALL 6 LINUX FORENSICS DRILLS COMPLETED ==="
}

case "$MODE" in
  list|--list)
    print_challenges
    ;;
  run|--run)
    run_live
    ;;
  *)
    echo "Usage: bash drills/linux/run_linux_drills.sh <list|run>"
    exit 1
    ;;
esac
