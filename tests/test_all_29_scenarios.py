"""Comprehensive anti-reskin & grading authenticity test across ALL 29 Firecracker chaos scenarios.

Proves two ironclad invariants for every single one of the 29 scenarios:
  1. When armed via arm_scenario_fault(), verify_workspace_checks() MUST FAIL (no pre-passing bugs).
  2. Fixing ONLY the base lab fault is NOT enough for specialized scenarios — each specialized
     scenario's own unique check MUST fail until its specific fault is remediated, and PASS once fixed.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from orchestrator.grader import arm_scenario_fault, provision_workspace, verify_workspace_checks
from orchestrator.scenarios_expanded import LAB_SCENARIO_CATALOG


def _fix_base_lab(root: Path, template_id: str) -> None:
    """Apply clean baseline remediation for a given lab template (without touching secondary scenario files)."""
    if template_id in {"lab1-core-engine", "lab11-p0-capstone"}:
        db = root / "data" / "orders.db"
        if db.exists():
            conn = sqlite3.connect(str(db))
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_tenant_created ON orders(tenant_id, created_at)")
            conn.commit()
            conn.close()
        pgb = root / "config" / "pgbouncer.ini"
        if pgb.exists():
            txt = pgb.read_text(encoding="utf-8")
            txt = txt.replace("default_pool_size = 2", "default_pool_size = 32")
            pgb.write_text(txt, encoding="utf-8")
    if template_id in {"lab2-linux-tls", "lab11-p0-capstone"}:
        up = root / "nginx" / "upstream.conf"
        if up.exists():
            up.write_text(up.read_text(encoding="utf-8").replace("keepalive_timeout 75s;", "keepalive_timeout 50s;"), encoding="utf-8")
        dep = root / "deploy" / "rollout.yaml"
        if dep.exists():
            dep.write_text(
                "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: edge-api\nspec:\n"
                "  replicas: 4\n  template:\n    spec:\n      containers:\n      - name: api\n"
                "        lifecycle:\n          preStop:\n            exec:\n              command: ['/bin/sh','-c','sleep 10']\n",
                encoding="utf-8",
            )
    if template_id == "lab3-lakehouse-wap":
        (root / "wap" / "publish_gate.py").write_text(
            "import json\nfrom pathlib import Path\n"
            "rows = [json.loads(l) for l in Path('wap/staging_batch.jsonl').read_text().splitlines() if l.strip()]\n"
            "good = [r for r in rows if isinstance(r.get('tenant_id'), str) and r['tenant_id'].strip()]\n"
            "bad = [r for r in rows if not (isinstance(r.get('tenant_id'), str) and r['tenant_id'].strip())]\n"
            "Path('wap/curated.jsonl').write_text('\\n'.join(json.dumps(r) for r in good) + '\\n')\n"
            "Path('wap/dlq.jsonl').write_text('\\n'.join(json.dumps(r) for r in bad) + '\\n')\n",
            encoding="utf-8",
        )
        pit = root / "wap" / "duckdb_pit_audit.py"
        if pit.exists():
            pit.write_text(
                pit.read_text(encoding="utf-8").replace(
                    "JOIN carrier_events e\n  ON s.shipment_id = e.shipment_id",
                    "ASOF JOIN carrier_events e\n  ON s.shipment_id = e.shipment_id AND s.pred_ts >= e.event_ts",
                ),
                encoding="utf-8",
            )
    if template_id == "lab4-rag-acl":
        provision_workspace(root, template_id, "sbx_fix", arm_fault=False)
    if template_id == "lab5-raft-internals":
        (root / "raft" / "storage_guard.py").write_text(
            "class FencedStorage:\n"
            "    def __init__(self):\n        self.high_water_token = 0\n        self.data = {}\n"
            "    def write(self, key, value, fencing_token):\n"
            "        if fencing_token < self.high_water_token:\n            return False\n"
            "        self.high_water_token = fencing_token\n        self.data[key] = value\n        return True\n",
            encoding="utf-8",
        )
    if template_id == "lab6-k8s-ebpf":
        (root / "k8s" / "networkpolicy.yaml").write_text(
            "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: api-egress\nspec:\n"
            "  policyTypes:\n    - Egress\n  egress:\n  - ports:\n      - protocol: TCP\n        port: 6432\n",
            encoding="utf-8",
        )
        (root / "k8s" / "pdb.yaml").write_text(
            "apiVersion: policy/v1\nkind: PodDisruptionBudget\nspec:\n  minAvailable: 75%\n",
            encoding="utf-8",
        )
    if template_id == "lab7-linux-sre":
        (root / "config" / "limits.conf").write_text("operator soft nofile 65535\noperator hard nofile 65535\n", encoding="utf-8")
        (root / "config" / "hosts.override").write_text("127.0.0.1 payments.internal\n", encoding="utf-8")
        lf = root / "run" / "worker.lock"
        if lf.exists():
            lf.unlink()
    if template_id == "lab8-scale-api":
        provision_workspace(root, template_id, "sbx_fix", arm_fault=False)
    if template_id == "lab9-iac-iam":
        (root / "iam" / "policy.json").write_text(
            json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::bucket/*"}]}),
            encoding="utf-8",
        )
        (root / "terraform" / "backend.tf").write_text(
            'terraform {\n  backend "s3" {\n    encrypt = true\n    dynamodb_table = "locks"\n  }\n}\n',
            encoding="utf-8",
        )
    if template_id == "lab10-ai-gpu-mcp":
        provision_workspace(root, template_id, "sbx_fix", arm_fault=False)


def _fix_secondary_scenario(root: Path, scenario_id: str) -> None:
    if scenario_id == "pgbouncer_session_mode_starvation":
        pgb = root / "config" / "pgbouncer.ini"
        txt = pgb.read_text(encoding="utf-8").replace("pool_mode = session", "pool_mode = transaction").replace("max_client_conn = 12", "max_client_conn = 500")
        pgb.write_text(txt, encoding="utf-8")
    elif scenario_id in {"redis_maxmemory_noeviction_oom", "principal_black_friday_cascade_p0"}:
        (root / "config" / "redis.conf").write_text("maxmemory 256mb\nmaxmemory-policy allkeys-lru\n", encoding="utf-8")
    elif scenario_id == "pg_blocking_lock_storm":
        (root / "config" / "postgres-guard.conf").write_text("idle_in_transaction_session_timeout = 15000\nlock_timeout = 2000\n", encoding="utf-8")
    elif scenario_id == "pg_wal_bloat_and_vacuum_freeze":
        (root / "config" / "postgres-guard.conf").write_text(
            "autovacuum_vacuum_scale_factor = 0.02\nmax_wal_size = 4096\nidle_in_transaction_session_timeout = 15000\n",
            encoding="utf-8",
        )
    elif scenario_id == "nginx_weak_tls_and_missing_hsts":
        (root / "nginx" / "security.conf").write_text(
            "ssl_protocols TLSv1.2 TLSv1.3;\nadd_header Strict-Transport-Security \"max-age=63072000\" always;\n",
            encoding="utf-8",
        )
    elif scenario_id == "nginx_413_body_and_worker_limit":
        (root / "nginx" / "upload.conf").write_text("client_max_body_size 25m;\nworker_connections 2048;\n", encoding="utf-8")
    elif scenario_id == "tc_netem_packet_loss_tail_collapse":
        (root / "config" / "netem.conf").write_text("loss_pct = 0.0\ndelay_ms = 5\ncongestion_control = bbr\n", encoding="utf-8")
    elif scenario_id == "wap_duplicate_event_idempotency":
        (root / "wap" / "publish_gate.py").write_text(
            "import json\nfrom pathlib import Path\n"
            "rows = [json.loads(l) for l in Path('wap/staging_batch.jsonl').read_text().splitlines() if l.strip()]\n"
            "seen, good, bad = set(), [], []\n"
            "for r in rows:\n"
            "    tid, eid = r.get('tenant_id'), r.get('event_id')\n"
            "    if isinstance(tid, str) and tid.strip() and eid not in seen:\n"
            "        seen.add(eid); good.append(r)\n"
            "    else:\n        bad.append(r)\n"
            "Path('wap/curated.jsonl').write_text('\\n'.join(json.dumps(r) for r in good) + '\\n')\n"
            "Path('wap/dlq.jsonl').write_text('\\n'.join(json.dumps(r) for r in bad) + '\\n')\n",
            encoding="utf-8",
        )
    elif scenario_id == "mcp_unbounded_agent_spend_loop":
        (root / "mcp" / "policy.json").write_text(
            json.dumps({"max_usd": 1.5, "max_steps": 8, "require_approval_for_writes": True, "allowed_tools": ["search_docs", "get_ticket"]}),
            encoding="utf-8",
        )
    elif scenario_id == "raft_gc_pause_stale_lease":
        (root / "raft" / "lease_config.json").write_text(json.dumps({"lease_ttl_ms": 5000, "require_storage_fencing": True}), encoding="utf-8")
    elif scenario_id == "raft_isr_lag_and_fencing_storm":
        (root / "raft" / "cluster.json").write_text(
            json.dumps({"replication_factor": 3, "min_insync_replicas": 2, "acks": "all", "unclean_leader_election": False}),
            encoding="utf-8",
        )
    elif scenario_id == "cilium_dns53_egress_blackhole":
        (root / "k8s" / "networkpolicy.yaml").write_text(
            "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: api-egress\nspec:\n"
            "  policyTypes:\n    - Egress\n  egress:\n  - ports:\n      - protocol: TCP\n        port: 6432\n      - protocol: UDP\n        port: 53\n",
            encoding="utf-8",
        )
    elif scenario_id == "linux_emfile_accept_storm":
        (root / "config" / "sysctl.conf").write_text("fs.file-max = 524288\nnet.core.somaxconn = 4096\n", encoding="utf-8")
    elif scenario_id == "cgroup_oom_kill_and_cpu_throttle":
        (root / "config" / "cgroup.conf").write_text("memory_max_mb = 1024\ncpu_quota_us = 80000\ncpu_period_us = 100000\n", encoding="utf-8")
    elif scenario_id == "tf_concurrent_state_corruption_and_passrole":
        (root / "iam" / "trust.json").write_text(
            json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::123456789012:role/ci"}, "Action": "sts:AssumeRole"}]}),
            encoding="utf-8",
        )


def test_all_29_scenarios_fail_armed_and_pass_remediated() -> None:
    total = 0
    for tpl_id, specs in LAB_SCENARIO_CATALOG.items():
        for spec in specs:
            total += 1
            with tempfile.TemporaryDirectory(prefix=f"crucible-29-{spec.scenario_id}-") as td:
                root = Path(td)
                arm_scenario_fault(root, tpl_id, f"sbx_{total}", scenario_id=spec.scenario_id)
                ok_armed, summary_armed, checks_armed = verify_workspace_checks(root, tpl_id)
                assert ok_armed is False, f"[{tpl_id}/{spec.scenario_id}] passed while armed! checks={checks_armed}"

                # Lab 9 special regression: comment '# encrypt = true' must NEVER make tf_lock pass
                if tpl_id == "lab9-iac-iam":
                    tf_chk = next(c for c in checks_armed if c["id"] == "tf_lock")
                    assert tf_chk["passed"] is False, "lab9 tf_lock false-passed on commented '# BUG: encrypt = true'!"

                # Apply base fix + secondary fix -> must PASS 100%
                _fix_base_lab(root, tpl_id)
                if spec.scenario_id in {
                    "pgbouncer_session_mode_starvation",
                    "redis_maxmemory_noeviction_oom",
                    "pg_blocking_lock_storm",
                    "pg_wal_bloat_and_vacuum_freeze",
                    "nginx_weak_tls_and_missing_hsts",
                    "nginx_413_body_and_worker_limit",
                    "tc_netem_packet_loss_tail_collapse",
                    "wap_duplicate_event_idempotency",
                    "raft_gc_pause_stale_lease",
                    "raft_isr_lag_and_fencing_storm",
                    "cilium_dns53_egress_blackhole",
                    "linux_emfile_accept_storm",
                    "cgroup_oom_kill_and_cpu_throttle",
                    "tf_concurrent_state_corruption_and_passrole",
                    "principal_black_friday_cascade_p0",
                }:
                    # Prove base fix alone is NOT enough!
                    ok_base_only, _, _ = verify_workspace_checks(root, tpl_id)
                    assert ok_base_only is False, f"[{tpl_id}/{spec.scenario_id}] passed with base fix alone — secondary fault wasn't graded!"

                _fix_secondary_scenario(root, spec.scenario_id)
                ok_fixed, summary_fixed, checks_fixed = verify_workspace_checks(root, tpl_id)
                assert ok_fixed is True, f"[{tpl_id}/{spec.scenario_id}] failed after remediation: {summary_fixed} checks={checks_fixed}"

    assert total == 29, f"Expected 29 chaos scenarios, tested {total}"
