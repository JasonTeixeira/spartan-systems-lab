"""Real runnable Linux War-Room workspaces, fault injectors, and SLA verifiers for Labs 1–6."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RealLabFault:
    fault_id: str
    symptom: str
    remediation_hint: str


LAB_FAULTS: dict[str, RealLabFault] = {
    "lab1-core-engine": RealLabFault(
        fault_id="pg_missing_index_and_pool_starvation",
        symptom=(
            "P1 ALERT: /api/orders p99 crossed 6.8s (SLO < 50ms) and PgBouncer "
            "wait queue is saturated. Inspect data/orders.db query plan & config/pgbouncer.ini."
        ),
        remediation_hint=(
            "Create composite index idx_orders_tenant_created ON orders(tenant_id, created_at) "
            "in data/orders.db and raise default_pool_size >= 25 in config/pgbouncer.ini."
        ),
    ),
    "lab2-linux-tls": RealLabFault(
        fault_id="keepalive_race_and_missing_prestop",
        symptom=(
            "P1 ALERT: Rolling deploy triggered 4.2% HTTP 502 resets on active HTTP/2 streams. "
            "Inspect nginx/upstream.conf keepalive_timeout and deploy/rollout.yaml drain hooks."
        ),
        remediation_hint=(
            "Set nginx upstream keepalive_timeout strictly lower than app idle timeout (<= 55s) "
            "and add a preStop sleep drain hook in deploy/rollout.yaml."
        ),
    ),
    "lab3-lakehouse-wap": RealLabFault(
        fault_id="wap_null_tenant_poison_publish",
        symptom=(
            "P1 ALERT: Executive BI shows corrupted NULL-tenant revenue rows after last batch. "
            "Inspect wap/staging_batch.jsonl and wap/publish_gate.py."
        ),
        remediation_hint=(
            "Fix wap/publish_gate.py to quarantine rows with null/empty tenant_id into "
            "wap/dlq.jsonl and publish only valid rows to wap/curated.jsonl, then run it."
        ),
    ),
    "lab4-rag-acl": RealLabFault(
        fault_id="rag_post_filter_acl_leak",
        symptom=(
            "P1 SECURITY ALERT: Small enterprise tenant receives 0 recall while red-team probe "
            "flags cross-tenant leakage risk. Inspect rag/retriever.py and run python3 rag/test_acl.py."
        ),
        remediation_hint=(
            "Move tenant_id ACL filtering BEFORE top_k slicing in rag/retriever.py and set "
            "max_usd <= 2.00 and max_steps <= 12 in mcp/policy.json."
        ),
    ),
    "lab5-raft-internals": RealLabFault(
        fault_id="raft_split_brain_zombie_write",
        symptom=(
            "P1 DATA INTEGRITY ALERT: Partitioned stale Raft leader (term 14) overwrote "
            "committed term 15 state. Inspect raft/storage_guard.py and run python3 raft/test_fencing.py."
        ),
        remediation_hint=(
            "Enforce strict monotonic fencing check (reject write if token < high_water_mark) "
            "in raft/storage_guard.py so zombie writes fail closed."
        ),
    ),
    "lab6-k8s-ebpf": RealLabFault(
        fault_id="cilium_egress_drop_and_pdb_stall",
        symptom=(
            "P1 ALERT: API pods cannot reach PgBouncer :6432 after Cilium policy rollout and "
            "node drain is stalled. Inspect k8s/networkpolicy.yaml and k8s/pdb.yaml."
        ),
        remediation_hint=(
            "Allow egress TCP port 6432 in k8s/networkpolicy.yaml and change k8s/pdb.yaml "
            "minAvailable from 100% to <= 80% (or maxUnavailable: 1)."
        ),
    ),
}


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _seed_lab1(root: Path, broken: bool) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(parents=True, exist_ok=True)

    pool_size = 2 if broken else 32
    (root / "config" / "pgbouncer.ini").write_text(
        f"[databases]\norders = host=127.0.0.1 port=5432 dbname=orders\n\n"
        f"[pgbouncer]\npool_mode = transaction\nmax_client_conn = 500\n"
        f"default_pool_size = {pool_size}\nquery_wait_timeout = 15\n",
        encoding="utf-8",
    )

    db_path = root / "data" / "orders.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "created_at TEXT NOT NULL, amount_cents INTEGER NOT NULL, status TEXT NOT NULL)"
        )
        rows = [
            (f"tenant_{i % 25:02d}", f"2026-11-{(i % 24) + 1:02d}T12:{i % 60:02d}:00Z", 1500 + (i % 9000), "paid")
            for i in range(1, 2501)
        ]
        conn.executemany(
            "INSERT INTO orders (tenant_id, created_at, amount_cents, status) VALUES (?, ?, ?, ?)",
            rows,
        )
        if not broken:
            conn.execute("CREATE INDEX idx_orders_tenant_created ON orders(tenant_id, created_at)")
        conn.commit()
    finally:
        conn.close()

    (root / "logs" / "db.log").write_text(
        (
            "2026-11-24T19:10:01Z WARN slow_query duration_ms=6840 sql=\"SELECT * FROM orders "
            "WHERE tenant_id='tenant_07' ORDER BY created_at DESC LIMIT 25\"\n"
            "2026-11-24T19:10:02Z ERROR pgbouncer cl_waiting=148 sv_active=2 default_pool_size=2\n"
        )
        if broken
        else "2026-11-24T19:10:01Z INFO query duration_ms=4.1 index=idx_orders_tenant_created\n",
        encoding="utf-8",
    )

    _write_executable(
        root / "bin" / "pg-xray",
        "#!/usr/bin/env bash\n"
        "echo '=== EXPLAIN QUERY PLAN (data/orders.db) ==='\n"
        "sqlite3 data/orders.db \"EXPLAIN QUERY PLAN SELECT id, amount_cents FROM orders WHERE tenant_id='tenant_07' ORDER BY created_at DESC LIMIT 25;\"\n"
        "echo ''\n"
        "echo '=== PgBouncer Pool Config ==='\n"
        "grep -E 'pool_mode|default_pool_size|max_client_conn' config/pgbouncer.ini\n",
    )


def _seed_lab2(root: Path, broken: bool) -> None:
    (root / "nginx").mkdir(parents=True, exist_ok=True)
    (root / "deploy").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    ka = 75 if broken else 50
    (root / "nginx" / "upstream.conf").write_text(
        f"upstream fastapi_backend {{\n"
        f"    server 10.0.1.12:8000;\n"
        f"    keepalive 64;\n"
        f"    # Upstream FastAPI idle timeout is 60s\n"
        f"    keepalive_timeout {ka}s;\n"
        f"}}\n",
        encoding="utf-8",
    )
    prestop = (
        "        # TODO: missing preStop drain hook\n"
        if broken
        else "        lifecycle:\n          preStop:\n            exec:\n              command: ['/bin/sh', '-c', 'sleep 10']\n"
    )
    (root / "deploy" / "rollout.yaml").write_text(
        f"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: edge-api\nspec:\n"
        f"  replicas: 4\n  template:\n    spec:\n      terminationGracePeriodSeconds: 30\n"
        f"      containers:\n      - name: api\n        image: sageideas/edge-api:2.4.1\n{prestop}",
        encoding="utf-8",
    )
    (root / "logs" / "tls.log").write_text(
        "ERROR upstream prematurely closed connection while reading response header (keepalive=75s > app=60s)\n"
        "WARN SIGTERM received before endpoint removal — 42 active requests reset (HTTP 502)\n"
        if broken
        else "INFO TLS 1.3 handshake nominal · zero 502 resets during rolling deploy\n",
        encoding="utf-8",
    )


def _seed_lab3(root: Path, broken: bool) -> None:
    (root / "wap").mkdir(parents=True, exist_ok=True)
    batch = [
        {"event_id": "evt_101", "tenant_id": "acme", "revenue_cents": 4900},
        {"event_id": "evt_102", "tenant_id": None, "revenue_cents": 9900},
        {"event_id": "evt_103", "tenant_id": "globex", "revenue_cents": 12900},
        {"event_id": "evt_104", "tenant_id": "", "revenue_cents": 4900},
        {"event_id": "evt_105", "tenant_id": "initech", "revenue_cents": 19900},
    ]
    (root / "wap" / "staging_batch.jsonl").write_text(
        "\n".join(json.dumps(r) for r in batch) + "\n", encoding="utf-8"
    )
    gate_code = (
        """#!/usr/bin/env python3
import json
from pathlib import Path

staging = Path("wap/staging_batch.jsonl")
curated = Path("wap/curated.jsonl")
dlq = Path("wap/dlq.jsonl")

rows = [json.loads(line) for line in staging.read_text().splitlines() if line.strip()]
# BUG: publishes raw staging rows straight to curated without auditing tenant_id!
curated.write_text("\\n".join(json.dumps(r) for r in rows) + "\\n")
dlq.write_text("")
print(f"Published {len(rows)} rows (0 quarantined)")
"""
        if broken
        else """#!/usr/bin/env python3
import json
from pathlib import Path

staging = Path("wap/staging_batch.jsonl")
curated = Path("wap/curated.jsonl")
dlq = Path("wap/dlq.jsonl")

good, bad = [], []
for line in staging.read_text().splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if isinstance(row.get("tenant_id"), str) and row["tenant_id"].strip():
        good.append(row)
    else:
        bad.append(row)

curated.write_text("\\n".join(json.dumps(r) for r in good) + "\\n")
dlq.write_text("\\n".join(json.dumps(r) for r in bad) + "\\n")
print(f"Published {len(good)} clean rows, quarantined {len(bad)} invalid rows to dlq.jsonl")
"""
    )
    _write_executable(root / "wap" / "publish_gate.py", gate_code)
    subprocess.run([sys.executable, "wap/publish_gate.py"], cwd=str(root), check=False)


def _seed_lab4(root: Path, broken: bool) -> None:
    (root / "rag").mkdir(parents=True, exist_ok=True)
    (root / "mcp").mkdir(parents=True, exist_ok=True)

    (root / "mcp" / "policy.json").write_text(
        json.dumps(
            {
                "max_usd": 500.0 if broken else 1.5,
                "max_steps": 999 if broken else 8,
                "require_approval_for_writes": not broken,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    retriever_code = (
        """from __future__ import annotations

def retrieve_for_tenant(docs: list[dict], tenant_id: str, top_k: int = 2) -> list[dict]:
    # BUG: slices top_k BEFORE tenant ACL filtering!
    ranked = sorted(docs, key=lambda d: d["score"], reverse=True)[:top_k]
    return [d for d in ranked if d["tenant_id"] == tenant_id]
"""
        if broken
        else """from __future__ import annotations

def retrieve_for_tenant(docs: list[dict], tenant_id: str, top_k: int = 2) -> list[dict]:
    # Pre-filter strictly by JWT tenant_id BEFORE top_k ranking
    scoped = [d for d in docs if d["tenant_id"] == tenant_id]
    return sorted(scoped, key=lambda d: d["score"], reverse=True)[:top_k]
"""
    )
    (root / "rag" / "retriever.py").write_text(retriever_code, encoding="utf-8")
    (root / "rag" / "test_acl.py").write_text(
        """#!/usr/bin/env python3
from retriever import retrieve_for_tenant

CORPUS = [
    {"id": "d1", "tenant_id": "mega_corp", "score": 0.99, "text": "MegaCorp M&A secret"},
    {"id": "d2", "tenant_id": "mega_corp", "score": 0.95, "text": "MegaCorp Q4 board"},
    {"id": "d3", "tenant_id": "small_co", "score": 0.82, "text": "SmallCo runbook A"},
    {"id": "d4", "tenant_id": "small_co", "score": 0.77, "text": "SmallCo runbook B"},
]

res = retrieve_for_tenant(CORPUS, tenant_id="small_co", top_k=2)
assert len(res) == 2, f"Expected 2 docs for small_co, got {len(res)} (post-filter starvation bug!)"
assert all(d["tenant_id"] == "small_co" for d in res), "Cross-tenant ACL leak!"
print("PASS: Pre-filter ACL verified (2/2 small_co docs, 0 leaks)")
""",
        encoding="utf-8",
    )


def _seed_lab5(root: Path, broken: bool) -> None:
    (root / "raft").mkdir(parents=True, exist_ok=True)
    guard_code = (
        """from __future__ import annotations

class FencedStorage:
    def __init__(self) -> None:
        self.high_water_token = 0
        self.data: dict[str, str] = {}

    def write(self, key: str, value: str, fencing_token: int) -> bool:
        # BUG: accepts writes from stale leaders with lower fencing_token!
        self.high_water_token = max(self.high_water_token, fencing_token)
        self.data[key] = value
        return True
"""
        if broken
        else """from __future__ import annotations

class FencedStorage:
    def __init__(self) -> None:
        self.high_water_token = 0
        self.data: dict[str, str] = {}

    def write(self, key: str, value: str, fencing_token: int) -> bool:
        if fencing_token < self.high_water_token:
            return False
        self.high_water_token = fencing_token
        self.data[key] = value
        return True
"""
    )
    (root / "raft" / "storage_guard.py").write_text(guard_code, encoding="utf-8")
    (root / "raft" / "test_fencing.py").write_text(
        """#!/usr/bin/env python3
from storage_guard import FencedStorage

store = FencedStorage()
assert store.write("balance", "500", fencing_token=15) is True
stale_ok = store.write("balance", "0_CORRUPT", fencing_token=14)
assert stale_ok is False, "Zombie leader token=14 was accepted! Split-brain corruption!"
assert store.data["balance"] == "500", "Committed term-15 value was overwritten!"
print("PASS: Monotonic fencing rejected stale leader term 14")
""",
        encoding="utf-8",
    )


def _seed_lab6(root: Path, broken: bool) -> None:
    (root / "k8s").mkdir(parents=True, exist_ok=True)
    port_block = (
        "      - protocol: TCP\n        port: 443\n      # BUG: PgBouncer port 6432 is blocked!\n"
        if broken
        else "      - protocol: TCP\n        port: 443\n      - protocol: TCP\n        port: 6432\n"
    )
    (root / "k8s" / "networkpolicy.yaml").write_text(
        f"apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: api-egress\nspec:\n"
        f"  podSelector:\n    matchLabels:\n      app: api\n  policyTypes: [Egress]\n"
        f"  egress:\n  - ports:\n{port_block}",
        encoding="utf-8",
    )
    min_avail = "100%" if broken else "75%"
    (root / "k8s" / "pdb.yaml").write_text(
        f"apiVersion: policy/v1\nkind: PodDisruptionBudget\nmetadata:\n  name: api-pdb\nspec:\n"
        f"  minAvailable: {min_avail}\n  selector:\n    matchLabels:\n      app: api\n",
        encoding="utf-8",
    )


def provision_workspace(
    root: Path, template_id: str, sandbox_id: str, arm_fault: bool = False
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(parents=True, exist_ok=True)

    seeders = {
        "lab1-core-engine": _seed_lab1,
        "lab2-linux-tls": _seed_lab2,
        "lab3-lakehouse-wap": _seed_lab3,
        "lab4-rag-acl": _seed_lab4,
        "lab5-raft-internals": _seed_lab5,
        "lab6-k8s-ebpf": _seed_lab6,
    }
    seeder = seeders.get(template_id, _seed_lab1)
    seeder(root, broken=arm_fault)

    fault = LAB_FAULTS[template_id]
    (root / "README.md").write_text(
        f"# CRUCIBLE LIVE LINUX WAR-ROOM · {template_id}\n"
        f"Sandbox ID: {sandbox_id}\n\n"
        f"## Incident Status\n"
        f"{'P1 BLIND OUTAGE ARMED — ' + fault.symptom if arm_fault else 'NOMINAL BASELINE (Healthy). Trigger Blind Outage to inject fault.'}\n\n"
        f"## Real Commands Available\n"
        f"- Standard Linux tools: ls, cat, grep, sed, awk, sqlite3, python3, jq, ss, ps, uname, openssl, curl\n"
        f"- Run `check-sla` anytime to run the real automated SLA probe against your workspace\n"
        f"- Run `hint` if you want a nudge toward the root cause\n",
        encoding="utf-8",
    )

    _write_executable(
        root / "bin" / "hint",
        f"#!/usr/bin/env bash\necho 'REMEDIATION HINT: {fault.remediation_hint}'\n",
    )
    _write_executable(
        root / "bin" / "check-sla",
        f"#!/usr/bin/env python3\n"
        f"import sys\n"
        f"sys.path.insert(0, '/srv/spartan-orchestrator')\n"
        f"from pathlib import Path\n"
        f"from orchestrator.lab_scenarios import verify_workspace_sla\n"
        f"ok, detail = verify_workspace_sla(Path('{root}'), '{template_id}')\n"
        f"print(('PASS: ' if ok else 'FAIL: ') + detail)\n"
        f"sys.exit(0 if ok else 1)\n",
    )


def arm_scenario_fault(root: Path, template_id: str, sandbox_id: str) -> RealLabFault:
    provision_workspace(root, template_id, sandbox_id, arm_fault=True)
    return LAB_FAULTS[template_id]


def verify_workspace_sla(root: Path, template_id: str) -> tuple[bool, str]:
    if not root.exists():
        return False, "sandbox workspace missing"

    if template_id == "lab1-core-engine":
        db_path = root / "data" / "orders.db"
        cfg_path = root / "config" / "pgbouncer.ini"
        if not db_path.exists() or not cfg_path.exists():
            return False, "orders.db or pgbouncer.ini missing"
        conn = sqlite3.connect(str(db_path))
        try:
            plan = " ".join(
                str(r)
                for r in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT id, amount_cents FROM orders "
                    "WHERE tenant_id='tenant_07' ORDER BY created_at DESC LIMIT 25"
                ).fetchall()
            )
        finally:
            conn.close()
        if "SEARCH" not in plan.upper():
            return False, f"orders query still doing full SCAN ({plan}); add composite index on (tenant_id, created_at)"
        cfg_text = cfg_path.read_text(encoding="utf-8")
        pool_val = 0
        for line in cfg_text.splitlines():
            if line.strip().startswith("default_pool_size"):
                try:
                    pool_val = int(line.split("=", 1)[1].strip())
                except ValueError:
                    pool_val = 0
        if pool_val < 25:
            return False, f"PgBouncer default_pool_size={pool_val} too low (need >= 25)"
        return True, f"SLA healthy: indexed query plan ({plan}) + default_pool_size={pool_val}"

    if template_id == "lab2-linux-tls":
        ng = (root / "nginx" / "upstream.conf").read_text(encoding="utf-8")
        dep = (root / "deploy" / "rollout.yaml").read_text(encoding="utf-8")
        ka = 999
        for line in ng.splitlines():
            s = line.strip()
            if s.startswith("keepalive_timeout"):
                raw = s.split()[1].rstrip("s;")
                if raw.isdigit():
                    ka = int(raw)
        if ka > 55:
            return False, f"nginx keepalive_timeout={ka}s exceeds safe threshold (<= 55s < 60s app idle)"
        if "preStop" not in dep:
            return False, "deploy/rollout.yaml is still missing a preStop drain hook"
        return True, f"SLA healthy: keepalive_timeout={ka}s and preStop drain hook active"

    if template_id == "lab3-lakehouse-wap":
        proc = subprocess.run(
            [sys.executable, "wap/publish_gate.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return False, f"publish_gate.py failed: {proc.stderr.strip()}"
        curated_path = root / "wap" / "curated.jsonl"
        dlq_path = root / "wap" / "dlq.jsonl"
        if not curated_path.exists() or not dlq_path.exists():
            return False, "wap/curated.jsonl or wap/dlq.jsonl missing"
        curated = [json.loads(l) for l in curated_path.read_text().splitlines() if l.strip()]
        dlq = [json.loads(l) for l in dlq_path.read_text().splitlines() if l.strip()]
        if any(not (isinstance(r.get("tenant_id"), str) and r["tenant_id"].strip()) for r in curated):
            return False, "wap/curated.jsonl still contains invalid/null tenant_id rows!"
        if len(curated) != 3 or len(dlq) != 2:
            return False, f"Expected 3 curated + 2 quarantined DLQ rows, got curated={len(curated)} dlq={len(dlq)}"
        return True, "SLA healthy: WAP gate published 3 clean rows and quarantined 2 corrupt rows to DLQ"

    if template_id == "lab4-rag-acl":
        proc = subprocess.run(
            [sys.executable, "rag/test_acl.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return False, f"ACL test failed: {(proc.stderr or proc.stdout).strip()}"
        policy = json.loads((root / "mcp" / "policy.json").read_text(encoding="utf-8"))
        if float(policy.get("max_usd", 999)) > 2.0 or int(policy.get("max_steps", 999)) > 12:
            return False, f"mcp/policy.json caps unsafe: max_usd={policy.get('max_usd')} max_steps={policy.get('max_steps')}"
        return True, "SLA healthy: pre-filter tenant ACL passed (0 leaks) + bounded MCP budget verified"

    if template_id == "lab5-raft-internals":
        proc = subprocess.run(
            [sys.executable, "raft/test_fencing.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return False, f"Fencing test failed: {(proc.stderr or proc.stdout).strip()}"
        return True, "SLA healthy: monotonic fencing token rejected stale term-14 leader write"

    if template_id == "lab6-k8s-ebpf":
        np_text = (root / "k8s" / "networkpolicy.yaml").read_text(encoding="utf-8")
        pdb_text = (root / "k8s" / "pdb.yaml").read_text(encoding="utf-8")
        if "6432" not in np_text:
            return False, "k8s/networkpolicy.yaml still blocks egress TCP port 6432 to PgBouncer"
        if "100%" in pdb_text:
            return False, "k8s/pdb.yaml minAvailable: 100% still blocks AZ node drains"
        return True, "SLA healthy: Cilium/K8s egress allows :6432 and PDB allows safe node drains"

    return False, f"unknown template {template_id}"
