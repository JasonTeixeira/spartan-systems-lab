#!/usr/bin/env bash
set -euo pipefail

SCENARIO="${1:-help}"
COMPOSE="docker compose -f lab-1-core-engine/docker-compose.yml"

case "$SCENARIO" in
  lock-storm)
    echo "[CHAOS] Holding ACCESS EXCLUSIVE lock on events table for 45 seconds..."
    echo "[HINT]  Open another terminal: make psql -> inspect pg_stat_activity and pg_locks!"
    $COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
      "BEGIN; LOCK TABLE events IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(45); COMMIT;"
    ;;
  net-latency)
    echo "[CHAOS] Injecting 250ms +/- 50ms latency & 5% packet loss on sre-toolbox eth0..."
    $COMPOSE exec -T sre-toolbox tc qdisc replace dev eth0 root netem delay 250ms 50ms loss 5%
    echo "[HINT]  Test with: make sre-shell -> curl -w '%{time_total}\n' -o /dev/null -s http://nginx/healthz"
    ;;
  clear-latency)
    echo "[CHAOS] Clearing tc netem rules on sre-toolbox eth0..."
    $COMPOSE exec -T sre-toolbox tc qdisc del dev eth0 root || true
    ;;
  *)
    echo "Usage: bash lab-1-core-engine/scripts/chaos_lab1.sh <lock-storm|net-latency|clear-latency>"
    exit 1
    ;;
esac
