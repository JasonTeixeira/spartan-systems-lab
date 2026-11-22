#!/usr/bin/env bash
# Spartan 60-Second Read-Only Linux Triage Collector (Brendan Gregg USE/TSA Loop)
# Safe on any Debian/Ubuntu/Rocky/RHEL Linux server or container.
set -euo pipefail

section() {
  printf "\n==================== %s ====================\n" "$1"
}

run_if_present() {
  local cmd="$1"
  shift
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" "$@" || true
  else
    echo "[skip] $cmd not installed"
  fi
}

section "1. HOST, KERNEL & LOAD (uptime / uname)"
uname -a
uptime
nproc 2>/dev/null || true

section "2. CGROUP v2 CPU THROTTLING & MEMORY LIMITS (Containers)"
if [ -r /sys/fs/cgroup/cpu.stat ]; then
  cat /sys/fs/cgroup/cpu.stat
fi
if [ -r /sys/fs/cgroup/memory.current ]; then
  echo "memory.current: $(cat /sys/fs/cgroup/memory.current)"
  echo "memory.max:     $(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo n/a)"
fi

section "3. MEMORY & SWAP (free -m)"
run_if_present free -m

section "4. DISK SPACE & INODE EXHAUSTION (df -h / df -i)"
df -h
echo "--- INODES ---"
df -i

section "5. CPU RUN QUEUE & I/O WAIT (vmstat 1 3)"
run_if_present vmstat 1 3

section "6. DISK SATURATION & AWAIT LATENCY (iostat -xz 1 2)"
run_if_present iostat -xz 1 2

section "7. SOCKET STATES & LISTENING PORTS (ss -s / ss -tulpn)"
run_if_present ss -s
run_if_present ss -tulpn

section "8. ROUTING TABLE & DNS RESOLVER (ip route / resolv.conf)"
run_if_present ip -br addr
run_if_present ip route
cat /etc/resolv.conf 2>/dev/null || true

section "9. UNINTERRUPTIBLE D-STATE & TOP CPU/MEM PROCESSES"
ps aux | awk 'NR==1 || $8 ~ /D/' | head -n 15
echo "--- TOP 10 BY RSS MEM ---"
ps aux --sort=-%mem 2>/dev/null | head -n 11 || ps aux | head -n 11

section "10. RECENT KERNEL ERRORS / OOM KILLER (dmesg)"
if command -v dmesg >/dev/null 2>&1; then
  dmesg -T 2>/dev/null | tail -n 20 || echo "[restricted] dmesg requires elevated privileges"
fi
