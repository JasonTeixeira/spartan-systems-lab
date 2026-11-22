#!/usr/bin/env bash
# Capture forensic evidence bundle BEFORE wiping/resetting a broken lab.
# Usage: bash scripts/snapshot_incident.sh <incident-slug>
set -euo pipefail

NAME="${1:-incident}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="docs/incidents/${STAMP}_${NAME}"
COMPOSE="docker compose -f lab-1-core-engine/docker-compose.yml"

mkdir -p "$OUT_DIR"

echo "Capturing incident evidence bundle into $OUT_DIR ..."

git rev-parse HEAD > "$OUT_DIR/git_commit.txt" 2>&1 || true
git status -s > "$OUT_DIR/git_status.txt" 2>&1 || true
git diff > "$OUT_DIR/git_diff.patch" 2>&1 || true

$COMPOSE ps -a > "$OUT_DIR/docker_ps.txt" 2>&1 || true
$COMPOSE logs --no-color --tail=200 > "$OUT_DIR/docker_logs.txt" 2>&1 || true

$COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
  "SELECT pid, state, wait_event_type, wait_event, age(clock_timestamp(), query_start) AS dur, left(query, 120) FROM pg_stat_activity WHERE datname='spartan_lab' ORDER BY dur DESC;" \
  > "$OUT_DIR/pg_stat_activity.txt" 2>&1 || true

$COMPOSE exec -T postgres psql -U spartan -d spartan_lab -c \
  "SELECT mode, granted, relation::regclass, pid FROM pg_locks WHERE relation IS NOT NULL;" \
  > "$OUT_DIR/pg_locks.txt" 2>&1 || true

$COMPOSE exec -T sre-toolbox bash -c \
  "echo '=== uptime ==='; uptime; echo '=== free -m ==='; free -m; echo '=== ss -s ==='; ss -s; echo '=== ip route ==='; ip route" \
  > "$OUT_DIR/linux_triage.txt" 2>&1 || true

cat <<EOF > "$OUT_DIR/README.md"
# Incident Evidence Bundle: ${NAME}

- **Captured (UTC):** ${STAMP}
- **Git Commit:** $(cat "$OUT_DIR/git_commit.txt")

## Captured Artifacts
- \`docker_ps.txt\` & \`docker_logs.txt\`
- \`pg_stat_activity.txt\` & \`pg_locks.txt\`
- \`linux_triage.txt\`
- \`git_status.txt\` & \`git_diff.patch\`

## Root Cause & Fix Summary
- **Symptom:**
- **Root Cause:**
- **Mitigation / Permanent Fix:**
- **MTTD / MTTR:**
EOF

echo "Saved evidence bundle -> $OUT_DIR"
