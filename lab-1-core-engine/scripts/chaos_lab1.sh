#!/usr/bin/env bash
set -euo pipefail

SCENARIO="${1:-help}"
COMPOSE="docker compose -f lab-1-core-engine/docker-compose.yml"

case "$SCENARIO" in
  lock-storm)
    echo "[CHAOS] Holding ACCESS EXCLUSIVE lock on events table for 45 seconds..."
    echo "[HINT]  Inspect pg_stat_activity and pg_locks via: make psql"
    $COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
      "BEGIN; LOCK TABLE events IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(45); COMMIT;"
    ;;
  net-latency)
    echo "[CHAOS] Injecting 250ms +/- 50ms latency & 5% packet loss on sre-toolbox eth0..."
    $COMPOSE exec -T sre-toolbox tc qdisc replace dev eth0 root netem delay 250ms 50ms loss 5%
    printf '%s\n' "[HINT]  Test with: make sre-shell -> curl -w '%{time_total}\n' -o /dev/null -s http://nginx/healthz"
    ;;
  idle-in-tx)
    echo "[CHAOS] Opening idle-in-transaction session holding row lock for 60 seconds..."
    $COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
      "BEGIN; SELECT id FROM tenants ORDER BY id LIMIT 1 FOR UPDATE; SELECT pg_sleep(60); ROLLBACK;"
    ;;
  pool-exhaustion)
    echo "[CHAOS] Saturating PgBouncer pool (25 concurrent pg_sleep(30) sessions)..."
    for _ in $(seq 1 25); do
      $COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c "SELECT pg_sleep(30);" >/dev/null 2>&1 &
    done
    echo "[HINT]  Check active connections in pg_stat_activity and PgBouncer stats."
    ;;
  redis-flush-stampede)
    echo "[CHAOS] Flushing Redis cache (FLUSHDB) to induce cold-cache DB stampede..."
    $COMPOSE exec -T redis redis-cli FLUSHDB
    ;;
  nginx-bad-upstream)
    echo "[CHAOS] Pausing spartan-api container to trigger edge 502/504 upstream failures..."
    docker pause spartan-api
    ;;
  seq-scan-bloat)
    echo "[CHAOS] Disabling index scans in spartan_lab to force full Seq Scans..."
    $COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
      "ALTER DATABASE spartan_lab SET enable_indexscan = off; ALTER DATABASE spartan_lab SET enable_bitmapscan = off;"
    ;;
  cpu-burn)
    echo "[CHAOS] Spawning 30-second CPU saturation workers inside sre-toolbox..."
    $COMPOSE exec -d sre-toolbox sh -c "timeout 30 sh -c 'yes > /dev/null & yes > /dev/null & wait'"
    ;;
  timeout-mismatch)
    echo "[CHAOS] Setting aggressive 5ms statement_timeout on spartan_lab..."
    $COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
      "ALTER DATABASE spartan_lab SET statement_timeout = '5ms';"
    ;;
  disk-fill)
    echo "[CHAOS] Allocating 64MB scratch artifact at /tmp/spartan-chaos-fill.bin inside sre-toolbox..."
    $COMPOSE exec -T sre-toolbox dd if=/dev/zero of=/tmp/spartan-chaos-fill.bin bs=1M count=64 status=none
    ;;
  clear-latency)
    echo "[CHAOS] Clearing tc netem rules on sre-toolbox eth0..."
    $COMPOSE exec -T sre-toolbox tc qdisc del dev eth0 root || true
    ;;
  clear-all)
    echo "[CHAOS] Clearing all 10 Lab 1 chaos faults..."
    $COMPOSE exec -T sre-toolbox tc qdisc del dev eth0 root 2>/dev/null || true
    $COMPOSE exec -T sre-toolbox rm -f /tmp/spartan-chaos-fill.bin 2>/dev/null || true
    $COMPOSE exec -T sre-toolbox pkill -f "yes" 2>/dev/null || true
    docker unpause spartan-api 2>/dev/null || true
    $COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
      "ALTER DATABASE spartan_lab RESET ALL;" 2>/dev/null || true
    $COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
      "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'spartan_lab' AND pid <> pg_backend_pid() AND query ILIKE '%pg_sleep%';" 2>/dev/null || true
    echo "[CHAOS] All faults cleared."
    ;;
  *)
    cat <<'EOF'
Usage: bash lab-1-core-engine/scripts/chaos_lab1.sh <scenario>

Available 10 production fault scenarios:
  lock-storm            Hold ACCESS EXCLUSIVE lock on events for 45s
  net-latency           Inject 250ms +/- 50ms latency & 5% loss on eth0
  idle-in-tx            Hold row-level FOR UPDATE lock idle-in-transaction for 60s
  pool-exhaustion       Spawn 25 concurrent pg_sleep(30) sessions to saturate pool
  redis-flush-stampede  Flush Redis cache to force cold-cache stampede
  nginx-bad-upstream    Pause spartan-api to induce edge 502/504 errors
  seq-scan-bloat        Disable index scans in Postgres to force Seq Scans
  cpu-burn              Saturate sre-toolbox CPU for 30s
  timeout-mismatch      Set 5ms statement_timeout on spartan_lab
  disk-fill             Write 64MB scratch file to /tmp inside sre-toolbox

Cleanup commands:
  clear-latency         Clear tc netem rules only
  clear-all             Safely remediate all 10 chaos faults
EOF
    exit 1
    ;;
esac
