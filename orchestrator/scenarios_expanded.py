"""Wave A Expanded Firecracker Labs (Labs 7-11) & Multi-Scenario Fault Catalog (24+ Incidents).

Provides dedicated real-world labs for EVERY Crucible module (M01 -> M12), including:
  - lab7-linux-sre       (M03: Linux ulimit/FD, stale lockfile, DNS override forensics)
  - lab8-scale-api       (M04: Sliding-window rate limiter & Idempotency-Key double-entry ledger)
  - lab9-iac-iam         (M06: AWS IAM least-privilege & Terraform encrypted state locking)
  - lab10-ai-gpu-mcp     (M09: MCP SSRF firewall & H100 vLLM KV-cache/prefix-cache tuning)
  - lab11-p0-capstone    (M12: Principal 3-layer cascading P0 across LIVE Postgres 16 + PgBouncer + NGINX TLS 1.3!)
Plus multi-scenario live faults for Lab 1 (Lock Storm, Redis OOM, PgBouncer Session Exhaustion)
and Lab 2 (Weak TLS 1.0 + Missing HSTS, NGINX 413 + Worker Limit).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    yaml = None

try:
    import psycopg  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    psycopg = None


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    template_id: str
    title: str
    difficulty: str
    symptom: str
    remediation_hint: str


# Multi-scenario catalog across all 11 Firecracker labs (24 distinct production incidents!)
LAB_SCENARIO_CATALOG: dict[str, list[ScenarioSpec]] = {
    "lab1-core-engine": [
        ScenarioSpec(
            scenario_id="pg_missing_index_and_pool_starvation",
            template_id="lab1-core-engine",
            title="Seq Scan + PgBouncer Pool Starvation",
            difficulty="L5",
            symptom="P1 ALERT: /api/orders p99 crossed 6.8s (SLO < 50ms) and PgBouncer wait queue is saturated. Inspect Postgres query plan (`pg-xray`) & config/pgbouncer.ini.",
            remediation_hint="Create composite index idx_orders_tenant_created ON orders(tenant_id, created_at) and raise default_pool_size >= 25 in config/pgbouncer.ini, then run reload-pgbouncer.",
        ),
        ScenarioSpec(
            scenario_id="pgbouncer_session_mode_starvation",
            template_id="lab1-core-engine",
            title="PgBouncer Session Mode Exhaustion",
            difficulty="L5",
            symptom="P1 ALERT: API pods receiving 'no more connections allowed (max_client_conn)' during burst traffic. Inspect config/pgbouncer.ini pool_mode & max_client_conn.",
            remediation_hint="Switch pool_mode from session to transaction and set max_client_conn >= 500 in config/pgbouncer.ini, then run reload-pgbouncer.",
        ),
        ScenarioSpec(
            scenario_id="redis_maxmemory_noeviction_oom",
            template_id="lab1-core-engine",
            title="Redis OOM noeviction Write Storm",
            difficulty="L5",
            symptom="P1 ALERT: Session & cache writes failing with OOM command not allowed when used memory > maxmemory. Inspect config/redis.conf and live Redis :6379.",
            remediation_hint="Set maxmemory-policy allkeys-lru in config/redis.conf and run `redis-cli CONFIG SET maxmemory-policy allkeys-lru`.",
        ),
        ScenarioSpec(
            scenario_id="pg_blocking_lock_storm",
            template_id="lab1-core-engine",
            title="Postgres Idle-in-Transaction Timeout Missing",
            difficulty="L6",
            symptom="P1 ALERT: Schema migration & checkout queries stalled behind idle-in-transaction locks. Inspect config/postgres-guard.conf and data/orders plan.",
            remediation_hint="Set idle_in_transaction_session_timeout <= 30000 (ms) and lock_timeout <= 5000 (ms) in config/postgres-guard.conf and ensure orders index is present.",
        ),
        ScenarioSpec(
            scenario_id="pg_wal_bloat_and_vacuum_freeze",
            template_id="lab1-core-engine",
            title="Postgres MVCC Dead-Tuple Bloat, WAL Spike & XID Wraparound",
            difficulty="L7",
            symptom="P1 STORAGE ALERT: orders table is 68% bloated with dead MVCC tuples, WAL disk growth hit 14GB/hr, and autovacuum cannot reclaim pages behind idle transactions. Inspect config/postgres-guard.conf & logs/pg_vacuum.log.",
            remediation_hint="Set autovacuum_vacuum_scale_factor <= 0.05, max_wal_size >= 2048 (MB), and idle_in_transaction_session_timeout <= 30000 in config/postgres-guard.conf, plus index orders(tenant_id, created_at) and raise PgBouncer pool >= 25.",
        ),
    ],
    "lab2-linux-tls": [
        ScenarioSpec(
            scenario_id="keepalive_race_and_missing_prestop",
            template_id="lab2-linux-tls",
            title="NGINX 502 Keepalive Race + Missing preStop",
            difficulty="L5",
            symptom="P1 ALERT: Rolling deploy triggered 4.2% HTTP 502 resets on active HTTP/2 streams. Inspect nginx/upstream.conf keepalive_timeout & deploy/rollout.yaml preStop.",
            remediation_hint="Set nginx upstream keepalive_timeout <= 55s (below 60s app idle), run reload-nginx, and add a lifecycle.preStop exec sleep drain hook in deploy/rollout.yaml.",
        ),
        ScenarioSpec(
            scenario_id="nginx_weak_tls_and_missing_hsts",
            template_id="lab2-linux-tls",
            title="Weak TLS 1.0/1.1 Downgrade + Missing HSTS",
            difficulty="L5",
            symptom="P1 SECURITY ALERT: Compliance scanner flagged deprecated TLSv1/TLSv1.1 ciphers and missing Strict-Transport-Security header on :8443. Inspect nginx/security.conf.",
            remediation_hint="Restrict ssl_protocols to TLSv1.2 TLSv1.3 only and add Strict-Transport-Security max-age >= 31536000 in nginx/security.conf, then run reload-nginx.",
        ),
        ScenarioSpec(
            scenario_id="nginx_413_body_and_worker_limit",
            template_id="lab2-linux-tls",
            title="NGINX 413 Upload Rejection + Worker Starvation",
            difficulty="L5",
            symptom="P1 ALERT: Enterprise webhook payloads failing with HTTP 413 Request Entity Too Large and worker_connections saturated. Inspect nginx/security.conf & nginx/upstream.conf.",
            remediation_hint="Raise client_max_body_size >= 10m in nginx/security.conf and ensure upstream keepalive_timeout <= 55s, then run reload-nginx.",
        ),
        ScenarioSpec(
            scenario_id="tc_netem_packet_loss_tail_collapse",
            template_id="lab2-linux-tls",
            title="TCP tc-netem 2.5% Packet Loss + Retry Storm Tail Collapse",
            difficulty="L7",
            symptom="P1 NETWORK ALERT: Cross-AZ link hit 2.5% packet loss under CUBIC congestion control, collapsing TCP throughput and causing an NGINX retry storm. Inspect config/netem.conf, nginx/upstream.conf & deploy/rollout.yaml.",
            remediation_hint="Switch congestion_control to bbr and clear loss_pct <= 0.1 in config/netem.conf, cap keepalive_timeout <= 55s in nginx/upstream.conf, and preserve lifecycle.preStop in deploy/rollout.yaml.",
        ),
    ],
    "lab3-lakehouse-wap": [
        ScenarioSpec(
            scenario_id="wap_null_tenant_poison_publish",
            template_id="lab3-lakehouse-wap",
            title="NULL Tenant Revenue Poisoning (WAP Gate)",
            difficulty="L5",
            symptom="P1 ALERT: Executive BI shows corrupted NULL/empty tenant revenue rows after last batch. Inspect wap/staging_batch.jsonl and fix wap/publish_gate.py.",
            remediation_hint="Quarantine rows with missing/null/empty tenant_id into wap/dlq.jsonl and publish only valid rows to wap/curated.jsonl.",
        ),
        ScenarioSpec(
            scenario_id="wap_duplicate_event_idempotency",
            template_id="lab3-lakehouse-wap",
            title="Duplicate Event Double-Counting (Idempotent WAP)",
            difficulty="L6",
            symptom="P1 ALERT: Retry replay doubled Q4 revenue in curated Iceberg table. Fix wap/publish_gate.py to deduplicate by event_id AND quarantine invalid tenant rows.",
            remediation_hint="Track seen event_ids in wap/publish_gate.py so duplicate events are routed to dlq.jsonl instead of double-counted in curated.jsonl.",
        ),
    ],
    "lab4-rag-acl": [
        ScenarioSpec(
            scenario_id="rag_post_filter_acl_leak",
            template_id="lab4-rag-acl",
            title="Post-Filter Tenant ACL Starvation & Budget Cap",
            difficulty="L6",
            symptom="P1 SECURITY ALERT: Small enterprise tenant receives 0 recall while red-team probe flags cross-tenant leakage risk. Fix rag/retriever.py and mcp/policy.json.",
            remediation_hint="Pre-filter docs strictly by tenant_id BEFORE top_k slicing in rag/retriever.py, and cap max_usd <= 2.00, max_steps <= 12, require_approval_for_writes=true in mcp/policy.json.",
        ),
        ScenarioSpec(
            scenario_id="mcp_unbounded_agent_spend_loop",
            template_id="lab4-rag-acl",
            title="Runaway MCP Agent Tool Loop & Budget Exhaustion",
            difficulty="L6",
            symptom="P1 FINOPS ALERT: Autonomous RAG agent burned $140 in 4 minutes on an unbounded tool retry loop without write approvals. Lock down mcp/policy.json & rag/retriever.py.",
            remediation_hint="Set max_usd <= 2.00, max_steps <= 12, require_approval_for_writes=true in mcp/policy.json and preserve pre-filter tenant ACLs in rag/retriever.py.",
        ),
    ],
    "lab5-raft-internals": [
        ScenarioSpec(
            scenario_id="raft_split_brain_zombie_write",
            template_id="lab5-raft-internals",
            title="Raft Split-Brain Zombie Leader Overwrite",
            difficulty="L6",
            symptom="P1 DATA INTEGRITY ALERT: Partitioned stale Raft leader (term 14) overwrote committed term 15 state. Fix monotonic fencing in raft/storage_guard.py.",
            remediation_hint="Reject writes whenever fencing_token < self.high_water_token in FencedStorage.write() so stale zombie leaders fail closed.",
        ),
        ScenarioSpec(
            scenario_id="raft_gc_pause_stale_lease",
            template_id="lab5-raft-internals",
            title="15s GC-Pause Stale Leader Lease Clobber",
            difficulty="L7",
            symptom="P1 DATA INTEGRITY ALERT: Old leader paused 15s in stop-the-world GC, woke up, and clobbered ledger rows written by term 16. Enforce monotonic fencing in raft/storage_guard.py.",
            remediation_hint="Check fencing_token < self.high_water_token at the storage boundary before mutating state in raft/storage_guard.py.",
        ),
        ScenarioSpec(
            scenario_id="raft_isr_lag_and_fencing_storm",
            template_id="lab5-raft-internals",
            title="Kafka ISR Shrink + Unfenced Raft Leader Failover",
            difficulty="L7",
            symptom="P1 CONSENSUS ALERT: Broker failover dropped 1,800 acked payment events because acks=1 & min_insync_replicas=1 allowed un-replicated commits while stale leader bypassed fencing. Fix raft/cluster.json & raft/storage_guard.py.",
            remediation_hint="Set acks='all' and min_insync_replicas >= 2 (with replication_factor >= 3) in raft/cluster.json and enforce monotonic fencing_token rejection in raft/storage_guard.py.",
        ),
    ],
    "lab6-k8s-ebpf": [
        ScenarioSpec(
            scenario_id="cilium_egress_drop_and_pdb_stall",
            template_id="lab6-k8s-ebpf",
            title="Cilium Egress :6432 Drop + PDB 100% Drain Deadlock",
            difficulty="L6",
            symptom="P1 ALERT: API pods cannot reach PgBouncer :6432 after Cilium policy rollout and AZ node drain is stalled. Fix k8s/networkpolicy.yaml and k8s/pdb.yaml.",
            remediation_hint="Allow TCP egress port 6432 in k8s/networkpolicy.yaml and change k8s/pdb.yaml minAvailable from 100% to <= 80% (or maxUnavailable: 1).",
        ),
        ScenarioSpec(
            scenario_id="cilium_dns53_egress_blackhole",
            template_id="lab6-k8s-ebpf",
            title="Zero-Trust Egress Blocking CoreDNS :53 + DB :6432",
            difficulty="L6",
            symptom="P1 ALERT: Default-deny NetworkPolicy dropped internal service discovery & PgBouncer egress while PDB minAvailable=100% froze rollout. Fix k8s/networkpolicy.yaml & k8s/pdb.yaml.",
            remediation_hint="Permit TCP:6432 and UDP/TCP:53 in k8s/networkpolicy.yaml and set safe drain budget in k8s/pdb.yaml.",
        ),
    ],
    "lab7-linux-sre": [
        ScenarioSpec(
            scenario_id="linux_fd_lockfile_and_dns_poison",
            template_id="lab7-linux-sre",
            title="FD Limit Exhaustion, Stale Lockfile & DNS Poisoning",
            difficulty="L5",
            symptom="P1 SRE ALERT: Worker daemon fails with 'Too many open files' + stale lockfile blocking restart while payments.internal resolves to blackhole 127.0.0.99.",
            remediation_hint="Raise nofile >= 65535 in config/limits.conf, remove stale run/worker.lock, and point payments.internal to 127.0.0.1 in config/hosts.override.",
        ),
        ScenarioSpec(
            scenario_id="linux_emfile_accept_storm",
            template_id="lab7-linux-sre",
            title="EMFILE Accept-Loop Collapse + Orphaned PID Lock",
            difficulty="L6",
            symptom="P1 SRE ALERT: Edge worker dropped into EMFILE accept loop under burst traffic and refuses restart due to orphaned PID 99999 lockfile. Fix config/limits.conf, run/worker.lock & config/hosts.override.",
            remediation_hint="Set nofile >= 65535, delete run/worker.lock, and restore payments.internal -> 127.0.0.1.",
        ),
        ScenarioSpec(
            scenario_id="cgroup_oom_kill_and_cpu_throttle",
            template_id="lab7-linux-sre",
            title="Linux cgroup v2 OOM-Kill (Exit 137) + CFS CPU Throttling",
            difficulty="L7",
            symptom="P1 KERNEL ALERT: Worker pods CrashLoopBackOff with Exit 137 (memory.max=128M) while surviving pods suffer 480ms p99 CFS throttling (cpu.max=5000 100000). Inspect config/cgroup.conf & logs/dmesg_oom.log.",
            remediation_hint="Raise memory_max_mb >= 512 and cpu_quota_us >= 50000 (out of 100000) in config/cgroup.conf, plus clear run/worker.lock, set nofile >= 65535, and fix payments.internal.",
        ),
    ],
    "lab8-scale-api": [
        ScenarioSpec(
            scenario_id="rate_limiter_and_idempotency_double_charge",
            template_id="lab8-scale-api",
            title="Rate Limiter Bypass + Payment Double-Charge Race",
            difficulty="L6",
            symptom="P1 FINTECH ALERT: Burst bots bypassed API rate limits and retried webhooks double-charged customer balances! Fix api/rate_limiter.py and api/ledger.py.",
            remediation_hint="Enforce per-key sliding-window max_requests in api/rate_limiter.py and deduplicate transactions by idempotency_key in api/ledger.py.",
        ),
        ScenarioSpec(
            scenario_id="hot_tenant_boundary_burst_and_retry",
            template_id="lab8-scale-api",
            title="Hot-Tenant 2x Window Burst + Webhook Retry Storm",
            difficulty="L6",
            symptom="P1 FINTECH ALERT: Enterprise tenant spiked 2x rate quota across minute boundaries while Stripe webhook retries double-debited wallets. Fix api/rate_limiter.py and api/ledger.py.",
            remediation_hint="Prune timestamps older than now - window_s per key in api/rate_limiter.py and return cached receipt for duplicate idempotency_key in api/ledger.py.",
        ),
    ],
    "lab9-iac-iam": [
        ScenarioSpec(
            scenario_id="iam_wildcard_privesc_and_tf_lock",
            template_id="lab9-iac-iam",
            title="IAM Wildcard Privilege Escalation + Unencrypted TF State",
            difficulty="L6",
            symptom="P1 SECOPS ALERT: Production CI role has Action:'*' / Resource:'*' privilege escalation and Terraform S3 backend lacks encryption & DynamoDB state locking!",
            remediation_hint="Remove wildcard '*' actions/resources in iam/policy.json (scope to least-privilege s3:GetObject/PutObject) and enable encrypt = true + dynamodb_table in terraform/backend.tf.",
        ),
        ScenarioSpec(
            scenario_id="tf_concurrent_state_corruption_and_passrole",
            template_id="lab9-iac-iam",
            title="Concurrent Terraform Apply Corruption + Wildcard IAM",
            difficulty="L6",
            symptom="P1 SECOPS ALERT: Two CI runs raced on unlocked S3 state while over-privileged role exposes cross-tenant buckets. Harden terraform/backend.tf and iam/policy.json.",
            remediation_hint="Enable encrypt = true + dynamodb_table state lock in terraform/backend.tf and replace '*' in iam/policy.json with scoped bucket ARN & least-privilege actions.",
        ),
    ],
    "lab10-ai-gpu-mcp": [
        ScenarioSpec(
            scenario_id="mcp_ssrf_metadata_and_vllm_kv_oom",
            template_id="lab10-ai-gpu-mcp",
            title="MCP Agent SSRF to AWS IMDS + H100 vLLM KV-Cache OOM",
            difficulty="L6",
            symptom="P1 AI-SEC ALERT: Red-team prompt tricked MCP fetch tool into reading http://169.254.169.254/latest/meta-data while H100 vLLM pods crash with CUDA OOM!",
            remediation_hint="Block private/loopback/link-local IPs & non-HTTPS schemes in mcp/url_guard.py, and set gpu_memory_utilization <= 0.90 + enable_prefix_caching: true in vllm/serve.yaml.",
        ),
        ScenarioSpec(
            scenario_id="vllm_prefix_cache_bust_and_rfc1918_pivot",
            template_id="lab10-ai-gpu-mcp",
            title="vLLM Prefix Cache Disabled (5x TTFT) + RFC1918 SSRF",
            difficulty="L7",
            symptom="P1 AI-INFRA ALERT: H100 TTFT jumped 5x with prefix caching off & OOM crashes while MCP tool allows internal 10.0.0.x scanning. Fix mcp/url_guard.py and vllm/serve.yaml.",
            remediation_hint="Enforce HTTPS-only public IP check in mcp/url_guard.py and set enable_prefix_caching: true with gpu_memory_utilization <= 0.90 in vllm/serve.yaml.",
        ),
    ],
    "lab11-p0-capstone": [
        ScenarioSpec(
            scenario_id="principal_three_layer_cascading_p0",
            template_id="lab11-p0-capstone",
            title="PRINCIPAL P0: Simultaneous NGINX + PgBouncer + Postgres 16 Meltdown",
            difficulty="L7",
            symptom="SEV-0 INCIDENT COMMAND: Three simultaneous production failures! Edge NGINX TLS :8443 throwing 502s (keepalive race), PgBouncer :6432 pool starved (pool=2), AND Postgres 16 orders table doing full Seq Scans!",
            remediation_hint="Fix ALL THREE live layers: (1) CREATE INDEX idx_orders_tenant_created ON orders(tenant_id, created_at DESC), (2) set default_pool_size >= 25 in config/pgbouncer.ini & reload-pgbouncer, (3) set keepalive_timeout <= 55s in nginx/upstream.conf & reload-nginx.",
        ),
        ScenarioSpec(
            scenario_id="principal_black_friday_cascade_p0",
            template_id="lab11-p0-capstone",
            title="PRINCIPAL SEV-0: Black Friday Edge-to-Disk Cascading Collapse",
            difficulty="L7",
            symptom="SEV-0 BLACK FRIDAY BRIDGE: 10x traffic surge exposed unindexed Postgres orders scan, starved PgBouncer pool, AND NGINX keepalive 502 resets simultaneously. Stabilize all 3 layers!",
            remediation_hint="Triage bottom-up: index Postgres orders(tenant_id, created_at DESC), raise PgBouncer default_pool_size >= 25 + reload-pgbouncer, lower NGINX keepalive_timeout <= 55s + reload-nginx + add K8s preStop.",
        ),
    ],
}


def _chk(cid: str, label: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": cid, "label": label, "passed": passed, "status": "pass" if passed else "fail", "detail": detail}


def list_all_scenarios() -> dict[str, list[dict[str, Any]]]:
    return {
        tpl_id: [asdict(s) for s in specs]
        for tpl_id, specs in LAB_SCENARIO_CATALOG.items()
    }


def get_scenario_spec(
    template_id: str,
    scenario_id: str | None = None,
    seed: int | None = None,
) -> ScenarioSpec:
    items = LAB_SCENARIO_CATALOG.get(template_id) or LAB_SCENARIO_CATALOG["lab1-core-engine"]
    if scenario_id and scenario_id.lower() == "random":
        rng = random.Random(seed) if seed is not None else random.SystemRandom()
        return rng.choice(items)
    if scenario_id:
        for s in items:
            if s.scenario_id == scenario_id:
                return s
    return items[0]


# ---------------------------------------------------------------------------
# Seeders & Immutable Graders for Labs 7 - 11
# ---------------------------------------------------------------------------

def seed_lab7(root: Path, broken: bool) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "run").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    nofile = 64 if broken else 65535
    (root / "config" / "limits.conf").write_text(
        f"# Crucible Worker OS Limits\n"
        f"operator soft nofile {nofile}\n"
        f"operator hard nofile {nofile}\n"
        f"operator soft nproc 4096\n",
        encoding="utf-8",
    )
    host_ip = "127.0.0.99" if broken else "127.0.0.1"
    (root / "config" / "hosts.override").write_text(
        f"# Internal service DNS overrides\n"
        f"{host_ip} payments.internal\n"
        f"127.0.0.1 telemetry.internal\n",
        encoding="utf-8",
    )
    lockfile = root / "run" / "worker.lock"
    if broken:
        lockfile.write_text("pid=99999 (STALE CRASHED WORKER — REMOVE TO UNBLOCK RESTART)\n", encoding="utf-8")
    elif lockfile.exists():
        lockfile.unlink()
    (root / "logs" / "sre.log").write_text(
        "ERROR accept4() failed: EMFILE (24: Too many open files, nofile=64)\n"
        "ERROR startup aborted: stale lockfile run/worker.lock held by dead pid 99999\n"
        "ERROR dial tcp 127.0.0.99:443 (payments.internal): connect: connection refused\n"
        if broken
        else "INFO worker nominal · nofile=65535 · payments.internal -> 127.0.0.1\n",
        encoding="utf-8",
    )
    (root / "bin").mkdir(parents=True, exist_ok=True)
    worker_bin = root / "bin" / "run-worker.py"
    worker_bin.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from pathlib import Path

root = Path.cwd()
if (root / "run" / "worker.lock").exists():
    print("FATAL: stale lockfile run/worker.lock exists", file=sys.stderr)
    sys.exit(2)

nofile = 0
for line in (root / "config" / "limits.conf").read_text(encoding="utf-8").splitlines():
    parts = line.split()
    if len(parts) >= 4 and parts[2] == "nofile" and parts[3].isdigit():
        nofile = max(nofile, int(parts[3]))
if nofile < 65535:
    print(f"FATAL: EMFILE nofile={nofile} < 65535", file=sys.stderr)
    sys.exit(3)

dns_ok = any(
    s and not s.startswith("#") and "payments.internal" in s and s.startswith("127.0.0.1")
    for s in (ln.strip() for ln in (root / "config" / "hosts.override").read_text(encoding="utf-8").splitlines())
)
if not dns_ok:
    print("FATAL: payments.internal does not resolve to 127.0.0.1", file=sys.stderr)
    sys.exit(4)

# Real OS file-descriptor pipe stress test (open 32 simultaneous pipe pairs = 64 live FDs)
pipes: list[tuple[int, int]] = []
try:
    for i in range(32):
        r_fd, w_fd = os.pipe()
        os.write(w_fd, b"ok")
        assert os.read(r_fd, 2) == b"ok"
        pipes.append((r_fd, w_fd))
finally:
    for r_fd, w_fd in pipes:
        os.close(r_fd)
        os.close(w_fd)

print(f"WORKER_READY nofile={nofile} fd_pipes_verified=64")
""",
        encoding="utf-8",
    )
    worker_bin.chmod(0o755)


def verify_lab7(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    lim_path = root / "config" / "limits.conf"
    nofile_val = 0
    if lim_path.exists():
        for line in lim_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "nofile" and parts[3].isdigit():
                nofile_val = max(nofile_val, int(parts[3]))
    fd_ok = nofile_val >= 65535
    checks.append(_chk("linux_nofile", "OS File Descriptor Limit (>= 65535)", fd_ok, f"nofile={nofile_val}" if fd_ok else f"nofile={nofile_val} too low (need >= 65535 in config/limits.conf)"))

    lock_ok = not (root / "run" / "worker.lock").exists()
    checks.append(_chk("linux_lock", "Stale Worker Lockfile Cleared", lock_ok, "run/worker.lock cleared" if lock_ok else "Stale run/worker.lock still blocking daemon start (`rm run/worker.lock`)"))

    hosts_path = root / "config" / "hosts.override"
    dns_ok = False
    if hosts_path.exists():
        for line in hosts_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "payments.internal" in s and s.startswith("127.0.0.1"):
                dns_ok = True
    checks.append(_chk("linux_dns", "payments.internal -> 127.0.0.1", dns_ok, "payments.internal resolves to 127.0.0.1" if dns_ok else "config/hosts.override still points payments.internal to wrong IP"))

    worker_bin = root / "bin" / "run-worker.py"
    if worker_bin.exists():
        wproc = subprocess.run(
            [sys.executable, "bin/run-worker.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=6,
        )
        w_ok = wproc.returncode == 0 and "WORKER_READY" in wproc.stdout
        checks.append(
            _chk(
                "linux_worker_exec",
                "Real Linux Worker Startup + 64-FD Pipe Stress",
                w_ok,
                wproc.stdout.strip()[:160] if w_ok else (wproc.stderr or wproc.stdout).strip()[:160],
            )
        )

    sysctl_path = root / "config" / "sysctl.conf"
    if sysctl_path.exists():
        skv: dict[str, int] = {}
        for line in sysctl_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                try:
                    skv[k.strip()] = int(v.strip())
                except ValueError:
                    pass
        fmax = skv.get("fs.file-max", 0)
        smax = skv.get("net.core.somaxconn", 0)
        sys_ok = fmax >= 262144 and smax >= 1024
        checks.append(
            _chk(
                "linux_sysctl",
                "Kernel fs.file-max (>=262144) & somaxconn (>=1024)",
                sys_ok,
                f"fs.file-max={fmax}, net.core.somaxconn={smax}"
                if sys_ok
                else f"Kernel accept backlog starved: fs.file-max={fmax} (>=262144), net.core.somaxconn={smax} (>=1024)",
            )
        )

    cg_path = root / "config" / "cgroup.conf"
    if cg_path.exists():
        ckv: dict[str, str] = {}
        for line in cg_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                ckv[k.strip()] = v.strip()
        try:
            mem_mb = int(float(ckv.get("memory_max_mb", "0")))
        except ValueError:
            mem_mb = 0
        try:
            cpu_q = int(float(ckv.get("cpu_quota_us", "0")))
        except ValueError:
            cpu_q = 0
        cg_ok = mem_mb >= 512 and cpu_q >= 50000
        checks.append(
            _chk(
                "linux_cgroup",
                "Linux cgroup v2 Memory (>=512MB) & CFS Quota (>=50ms)",
                cg_ok,
                f"memory_max_mb={mem_mb}, cpu_quota_us={cpu_q}"
                if cg_ok
                else f"Unsafe cgroup limits: memory_max_mb={mem_mb} (>=512), cpu_quota_us={cpu_q} (>=50000)",
            )
        )

    all_ok = all(c["passed"] for c in checks)
    return all_ok, ("SLA healthy: Linux FD limits (>=65535), stale lock cleared & DNS restored" if all_ok else next(c["detail"] for c in checks if not c["passed"])), checks


def seed_lab8(root: Path, broken: bool) -> None:
    (root / "api").mkdir(parents=True, exist_ok=True)
    rl_code = (
        """from __future__ import annotations

class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.hits: dict[str, list[float]] = {}

    def allow(self, client_key: str, now_ts: float) -> bool:
        # BUG: never enforces max_requests or evicts expired timestamps!
        self.hits.setdefault(client_key, []).append(now_ts)
        return True
"""
        if broken
        else """from __future__ import annotations

class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.hits: dict[str, list[float]] = {}

    def allow(self, client_key: str, now_ts: float) -> bool:
        cutoff = now_ts - self.window_seconds
        recent = [t for t in self.hits.get(client_key, []) if t > cutoff]
        if len(recent) >= self.max_requests:
            self.hits[client_key] = recent
            return False
        recent.append(now_ts)
        self.hits[client_key] = recent
        return True
"""
    )
    ledger_code = (
        """from __future__ import annotations

class PaymentLedger:
    def __init__(self) -> None:
        self.balances_cents: dict[str, int] = {}
        self.seen_keys: dict[str, dict] = {}

    def charge(self, account_id: str, amount_cents: int, idempotency_key: str) -> dict:
        # BUG: ignores idempotency_key, causing duplicate charges on webhook retries!
        self.balances_cents[account_id] = self.balances_cents.get(account_id, 0) + amount_cents
        return {"account_id": account_id, "charged_cents": amount_cents, "duplicate": False}
"""
        if broken
        else """from __future__ import annotations
import threading

class PaymentLedger:
    def __init__(self) -> None:
        self.balances_cents: dict[str, int] = {}
        self.seen_keys: dict[str, dict] = {}
        self._lock = threading.Lock()

    def charge(self, account_id: str, amount_cents: int, idempotency_key: str) -> dict:
        with self._lock:
            if idempotency_key in self.seen_keys:
                prev = dict(self.seen_keys[idempotency_key])
                prev["duplicate"] = True
                return prev
            self.balances_cents[account_id] = self.balances_cents.get(account_id, 0) + amount_cents
            receipt = {"account_id": account_id, "charged_cents": amount_cents, "duplicate": False}
            self.seen_keys[idempotency_key] = receipt
            return receipt
"""
    )
    (root / "api" / "rate_limiter.py").write_text(rl_code, encoding="utf-8")
    (root / "api" / "ledger.py").write_text(ledger_code, encoding="utf-8")


def verify_lab8(root: Path, env_fn: Any, preexec_fn: Any) -> tuple[bool, str, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    rl_test = """
import sys; sys.path.insert(0, "api")
from rate_limiter import SlidingWindowLimiter
lim = SlidingWindowLimiter(max_requests=3, window_seconds=10.0)
assert lim.allow("bot", 1.0) is True
assert lim.allow("bot", 2.0) is True
assert lim.allow("bot", 3.0) is True
assert lim.allow("bot", 4.0) is False, "4th request inside 10s window should be rejected!"
assert lim.allow("other_user", 4.0) is True, "Per-client isolation broken!"
assert lim.allow("bot", 12.5) is True, "Expired window should allow requests again!"
""" + (
        """
# Strict 2x window boundary burst test (fixed-window buckets fail this!)
b = SlidingWindowLimiter(max_requests=3, window_seconds=10.0)
assert b.allow("whale", 9.8) is True
assert b.allow("whale", 9.9) is True
assert b.allow("whale", 9.95) is True
assert b.allow("whale", 10.05) is False, "2x boundary burst across t=10.0 slipped through!"
assert b.allow("whale", 19.85) is True
"""
        if (root / "api" / "strict_boundary.flag").exists()
        else ""
    ) + 'print("RL_PASS")\n'
    p1 = subprocess.run([sys.executable, "-c", rl_test], cwd=str(root), env=env_fn(root), preexec_fn=preexec_fn(), capture_output=True, text=True, timeout=8)
    rl_ok = p1.returncode == 0 and "RL_PASS" in p1.stdout
    checks.append(_chk("scale_rl", "Sliding-Window Rate Limiter (Hidden Burst Test)", rl_ok, "Enforces per-key sliding window cleanly" if rl_ok else (p1.stderr or p1.stdout).strip()[:180]))

    led_test = """
import sys, threading; sys.path.insert(0, "api")
from ledger import PaymentLedger
lg = PaymentLedger()
r1 = lg.charge("acct_1", 7900, "idem_abc")
r2 = lg.charge("acct_1", 7900, "idem_abc")
r3 = lg.charge("acct_1", 1900, "idem_def")
assert lg.balances_cents["acct_1"] == 9800, f"Double-charge bug! Balance={lg.balances_cents['acct_1']} expected 9800"

# Real 16-thread concurrent webhook retry race test
barrier = threading.Barrier(16)
results = []
def worker():
    barrier.wait()
    results.append(lg.charge("acct_race", 5000, "idem_race_1"))
threads = [threading.Thread(target=worker) for _ in range(16)]
for t in threads: t.start()
for t in threads: t.join()
assert len(results) == 16
assert lg.balances_cents.get("acct_race") == 5000, f"Concurrent race double-charge! got {lg.balances_cents.get('acct_race')}"
print("LEDGER_PASS")
"""
    p2 = subprocess.run([sys.executable, "-c", led_test], cwd=str(root), env=env_fn(root), preexec_fn=preexec_fn(), capture_output=True, text=True, timeout=8)
    led_ok = p2.returncode == 0 and "LEDGER_PASS" in p2.stdout
    checks.append(_chk("scale_ledger", "Idempotent Payment Ledger (16-Thread Concurrency Race)", led_ok, "Idempotency-Key dedup & 16-thread race verified (balance=9800, race=5000)" if led_ok else (p2.stderr or p2.stdout).strip()[:180]))

    all_ok = all(c["passed"] for c in checks)
    return all_ok, ("SLA healthy: Sliding-window rate limiter & idempotent payment ledger passed hidden tests" if all_ok else next(c["detail"] for c in checks if not c["passed"])), checks


def seed_lab9(root: Path, broken: bool) -> None:
    (root / "iam").mkdir(parents=True, exist_ok=True)
    (root / "terraform").mkdir(parents=True, exist_ok=True)
    policy = (
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DangerousAdminWildcard",
                    "Effect": "Allow",
                    "Action": ["*", "iam:PassRole"],
                    "Resource": "*",
                }
            ],
        }
        if broken
        else {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "LeastPrivilegeArtifacts",
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:PutObject"],
                    "Resource": "arn:aws:s3:::crucible-prod-artifacts/*",
                }
            ],
        }
    )
    (root / "iam" / "policy.json").write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    tf_backend = (
        'terraform {\n  backend "s3" {\n    bucket = "crucible-tf-state"\n    key    = "prod/terraform.tfstate"\n    region = "us-east-1"\n    # BUG: encrypt = true and dynamodb_table state locking missing!\n  }\n}\n'
        if broken
        else 'terraform {\n  backend "s3" {\n    bucket         = "crucible-tf-state"\n    key            = "prod/terraform.tfstate"\n    region         = "us-east-1"\n    encrypt        = true\n    dynamodb_table = "crucible-tf-locks"\n  }\n}\n'
    )
    (root / "terraform" / "backend.tf").write_text(tf_backend, encoding="utf-8")


def verify_lab9(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    pol_path = root / "iam" / "policy.json"
    iam_ok = False
    iam_detail = "iam/policy.json missing"
    if pol_path.exists():
        try:
            doc = json.loads(pol_path.read_text(encoding="utf-8"))
            stmts = doc.get("Statement", [])
            bad = []
            for st in stmts:
                acts = st.get("Action", [])
                if isinstance(acts, str):
                    acts = [acts]
                res = st.get("Resource", [])
                if isinstance(res, str):
                    res = [res]
                if any(a in {"*", "iam:*", "iam:PassRole"} for a in acts):
                    bad.append("wildcard/privesc Action")
                if any(r == "*" for r in res):
                    bad.append("wildcard Resource '*'")
            iam_ok = bool(stmts) and not bad
            iam_detail = "Least-privilege IAM policy verified (0 wildcards)" if iam_ok else f"IAM policy still violates least privilege: {', '.join(bad)}"
        except ValueError as exc:
            iam_detail = f"Invalid JSON in iam/policy.json: {exc}"
    checks.append(_chk("iam_lp", "IAM Least-Privilege (No Wildcard / PassRole)", iam_ok, iam_detail))

    tf_path = root / "terraform" / "backend.tf"
    tf_ok = False
    tf_detail = "terraform/backend.tf missing"
    if tf_path.exists():
        # Strip HCL comments (# and //) before checking so '# BUG: encrypt = true' never false-passes!
        raw_lines = [
            re.sub(r"(#|//).*$", "", line)
            for line in tf_path.read_text(encoding="utf-8").splitlines()
        ]
        txt = "\n".join(raw_lines)
        has_enc = bool(re.search(r"\bencrypt\s*=\s*true\b", txt))
        has_lock = bool(re.search(r'\bdynamodb_table\s*=\s*"[^"]+"', txt)) or bool(re.search(r"\buse_lockfile\s*=\s*true\b", txt))
        tf_ok = has_enc and has_lock
        tf_detail = "Terraform S3 backend encrypted + state locking enabled" if tf_ok else "terraform/backend.tf missing active encrypt = true and/or dynamodb_table state lock (comments ignored)"
    checks.append(_chk("tf_lock", "Terraform State Encryption & Locking", tf_ok, tf_detail))

    trust_path = root / "iam" / "trust.json"
    if trust_path.exists():
        trust_ok = False
        trust_detail = "Invalid JSON in iam/trust.json"
        try:
            tdoc = json.loads(trust_path.read_text(encoding="utf-8"))
            tstmts = tdoc.get("Statement", [])
            has_wild = any(
                st.get("Principal") == "*"
                or (isinstance(st.get("Principal"), dict) and "*" in str(st.get("Principal")))
                for st in tstmts
            )
            trust_ok = bool(tstmts) and not has_wild
            trust_detail = "Scoped IAM trust principal verified" if trust_ok else "iam/trust.json still allows wildcard Principal '*'"
        except ValueError as exc:
            trust_detail = f"Invalid JSON in iam/trust.json: {exc}"
        checks.append(_chk("iam_trust", "IAM Trust Policy (No Wildcard Principal)", trust_ok, trust_detail))

    all_ok = all(c["passed"] for c in checks)
    return all_ok, ("SLA healthy: IAM least-privilege & encrypted Terraform state locking verified" if all_ok else next(c["detail"] for c in checks if not c["passed"])), checks


def seed_lab10(root: Path, broken: bool) -> None:
    (root / "mcp").mkdir(parents=True, exist_ok=True)
    (root / "vllm").mkdir(parents=True, exist_ok=True)
    guard_code = (
        """from __future__ import annotations
from urllib.parse import urlparse

def is_safe_egress_url(url: str) -> bool:
    # BUG: allows HTTP and internal metadata/loopback SSRF (169.254.169.254, 127.0.0.1, localhost)!
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)
"""
        if broken
        else """from __future__ import annotations
import ipaddress
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata"}

def is_safe_egress_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower().strip(".")
    if host in BLOCKED_HOSTS or host.endswith(".internal") or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        pass
    return True
"""
    )
    (root / "mcp" / "url_guard.py").write_text(guard_code, encoding="utf-8")
    vllm_cfg = (
        "model: meta-llama/Llama-3.1-70B-Instruct\ntensor_parallel_size: 4\ngpu_memory_utilization: 0.99\nenable_prefix_caching: false\nmax_num_seqs: 512\n"
        if broken
        else "model: meta-llama/Llama-3.1-70B-Instruct\ntensor_parallel_size: 4\ngpu_memory_utilization: 0.88\nenable_prefix_caching: true\nmax_num_seqs: 256\n"
    )
    (root / "vllm" / "serve.yaml").write_text(vllm_cfg, encoding="utf-8")


def verify_lab10(root: Path, env_fn: Any, preexec_fn: Any) -> tuple[bool, str, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    strict_rfc = (root / "vllm" / "strict_rfc1918.flag").exists()
    extra_bad = (
        '"https://172.16.0.5/admin", "https://192.168.1.1/router", "https://[::1]/internal",'
        if strict_rfc
        else ""
    )
    ssrf_test = f"""
import sys; sys.path.insert(0, "mcp")
from url_guard import is_safe_egress_url
for bad in [
    "http://169.254.169.254/latest/meta-data/",
    "https://169.254.169.254/latest/meta-data/",
    "https://127.0.0.1:8000/admin",
    "https://localhost/internal",
    "https://10.0.1.5/secrets",
    "http://docs.python.org/",
    "https://metadata.google.internal/computeMetadata/v1/",
    {extra_bad}
]:
    assert is_safe_egress_url(bad) is False, f"SSRF bypass allowed: {{bad}}"
assert is_safe_egress_url("https://api.github.com/repos") is True, "Valid HTTPS public URL blocked!"
print("SSRF_PASS")
"""
    p = subprocess.run([sys.executable, "-c", ssrf_test], cwd=str(root), env=env_fn(root), preexec_fn=preexec_fn(), capture_output=True, text=True, timeout=8)
    ssrf_ok = p.returncode == 0 and "SSRF_PASS" in p.stdout
    checks.append(_chk("mcp_ssrf", "MCP SSRF Firewall (Hidden Red-Team Suite)", ssrf_ok, "Blocked IMDS/loopback/RFC1918 & non-HTTPS; allowed public HTTPS" if ssrf_ok else (p.stderr or p.stdout).strip()[:180]))

    vllm_path = root / "vllm" / "serve.yaml"
    vllm_ok = False
    vllm_detail = "vllm/serve.yaml missing"
    if vllm_path.exists():
        raw = vllm_path.read_text(encoding="utf-8")
        if yaml is not None:
            try:
                doc = yaml.safe_load(raw)
                util = float(doc.get("gpu_memory_utilization", 1.0))
                prefix = doc.get("enable_prefix_caching") is True
                max_seqs = int(doc.get("max_num_seqs", 256))
                seqs_ok = (not strict_rfc) or max_seqs <= 256
                vllm_ok = util <= 0.92 and prefix and seqs_ok
                vllm_detail = (
                    f"gpu_memory_utilization={util}, prefix_caching=true, max_num_seqs={max_seqs}"
                    if vllm_ok
                    else f"Unsafe vLLM config: gpu_memory_utilization={util} (<=0.92), enable_prefix_caching={prefix}, max_num_seqs={max_seqs} (<=256)"
                )
            except Exception as exc:
                vllm_detail = f"Invalid YAML: {exc}"
        else:
            vllm_ok = "0.99" not in raw and "enable_prefix_caching: true" in raw
            vllm_detail = "vLLM KV-cache safe" if vllm_ok else "Fix gpu_memory_utilization and enable_prefix_caching"
    checks.append(_chk("vllm_kv", "H100 vLLM KV-Cache & Prefix Caching", vllm_ok, vllm_detail))

    all_ok = all(c["passed"] for c in checks)
    return all_ok, ("SLA healthy: MCP SSRF firewall passed red-team suite + H100 vLLM KV-cache tuned" if all_ok else next(c["detail"] for c in checks if not c["passed"])), checks
