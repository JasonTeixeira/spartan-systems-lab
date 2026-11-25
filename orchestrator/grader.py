"""Tamper-proof Crucible Lab Provisioner, Real Daemon Manager & Immutable SLA Grader.

Designed to live under `/opt/crucible-grader` (root:root 0700) inside each hardware-isolated
Firecracker MicroVM so the unprivileged `operator` shell user cannot read or alter grading logic,
hidden test datasets, or service verification probes.

Supports two execution modes automatically:
  1. `firecracker-real-daemons` (inside Firecracker MicroVM with Postgres 16, PgBouncer,
     Redis, NGINX, OpenSSL, Uvicorn installed): boots real production daemons and grades live
     database plans, live PgBouncer pool config, live TLS/NGINX responses, and hidden tests.
  2. `workspace-lite` (macOS / lightweight CI pytest without root daemons): uses SQLite +
     isolated scrubbed subprocesses with the exact same immutable hidden-test grading rules.
"""
from __future__ import annotations

import json
import os
import pwd
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
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
class RealLabFault:
    fault_id: str
    symptom: str
    remediation_hint: str


LAB_FAULTS: dict[str, RealLabFault] = {
    "lab1-core-engine": RealLabFault(
        fault_id="pg_missing_index_and_pool_starvation",
        symptom=(
            "P1 ALERT: /api/orders p99 crossed 6.8s (SLO < 50ms) and PgBouncer "
            "wait queue is saturated. Inspect Postgres query plan (`pg-xray`) & config/pgbouncer.ini."
        ),
        remediation_hint=(
            "Create composite index idx_orders_tenant_created ON orders(tenant_id, created_at) "
            "and raise default_pool_size >= 25 in config/pgbouncer.ini, then run reload-pgbouncer."
        ),
    ),
    "lab2-linux-tls": RealLabFault(
        fault_id="keepalive_race_and_missing_prestop",
        symptom=(
            "P1 ALERT: Rolling deploy triggered 4.2% HTTP 502 resets on active HTTP/2 streams. "
            "Inspect nginx/upstream.conf keepalive_timeout (and reload-nginx) + deploy/rollout.yaml preStop."
        ),
        remediation_hint=(
            "Set nginx upstream keepalive_timeout <= 55s (below app idle 60s), run reload-nginx, "
            "and add a lifecycle.preStop exec sleep drain hook in deploy/rollout.yaml."
        ),
    ),
    "lab3-lakehouse-wap": RealLabFault(
        fault_id="wap_null_tenant_poison_publish",
        symptom=(
            "P1 ALERT: Executive BI shows corrupted NULL/empty tenant revenue rows after last batch. "
            "Inspect wap/staging_batch.jsonl and fix wap/publish_gate.py."
        ),
        remediation_hint=(
            "Update wap/publish_gate.py to quarantine rows with missing/null/empty tenant_id "
            "or negative revenue_cents into wap/dlq.jsonl and publish only valid rows to wap/curated.jsonl."
        ),
    ),
    "lab4-rag-acl": RealLabFault(
        fault_id="rag_post_filter_acl_leak",
        symptom=(
            "P1 SECURITY ALERT: Small enterprise tenant receives 0 recall while red-team probe "
            "flags cross-tenant leakage risk. Fix rag/retriever.py and mcp/policy.json."
        ),
        remediation_hint=(
            "Pre-filter docs strictly by tenant_id BEFORE sorting/slicing top_k in rag/retriever.py, "
            "and set max_usd <= 2.00, max_steps <= 12, require_approval_for_writes=true in mcp/policy.json."
        ),
    ),
    "lab5-raft-internals": RealLabFault(
        fault_id="raft_split_brain_zombie_write",
        symptom=(
            "P1 DATA INTEGRITY ALERT: Partitioned stale Raft leader (term 14) overwrote "
            "committed term 15 state. Fix monotonic fencing in raft/storage_guard.py."
        ),
        remediation_hint=(
            "Reject writes whenever fencing_token < self.high_water_token in FencedStorage.write() "
            "so stale zombie leaders fail closed without mutating state."
        ),
    ),
    "lab6-k8s-ebpf": RealLabFault(
        fault_id="cilium_egress_drop_and_pdb_stall",
        symptom=(
            "P1 ALERT: API pods cannot reach PgBouncer :6432 after Cilium policy rollout and "
            "AZ node drain is stalled. Fix k8s/networkpolicy.yaml and k8s/pdb.yaml."
        ),
        remediation_hint=(
            "Add TCP egress port 6432 (and DNS 53) in k8s/networkpolicy.yaml and change k8s/pdb.yaml "
            "minAvailable from 100% to <= 80% (or set maxUnavailable: 1)."
        ),
    ),
}


def has_real_postgres() -> bool:
    return (
        os.geteuid() == 0
        and shutil.which("psql") is not None
        and shutil.which("pgbouncer") is not None
        and psycopg is not None
    )


def has_real_nginx() -> bool:
    return os.geteuid() == 0 and shutil.which("nginx") is not None


def _operator_ids() -> tuple[int, int] | None:
    try:
        pw = pwd.getpwnam("operator")
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        return None


def _chown_tree(path: Path) -> None:
    if os.geteuid() != 0:
        return
    ids = _operator_ids()
    if not ids:
        return
    uid, gid = ids
    for root, dirs, files in os.walk(path):
        with _suppress_os():
            os.chown(root, uid, gid)
        for d in dirs:
            with _suppress_os():
                os.chown(os.path.join(root, d), uid, gid)
        for f in files:
            with _suppress_os():
                os.chown(os.path.join(root, f), uid, gid)


class _suppress_os:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, _exc: Any, _tb: Any) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _wait_port(port: int, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.15)
    return False


def _scrubbed_subprocess_env(cwd: Path) -> dict[str, str]:
    """Never leak orchestrator or VM secrets into untrusted user script verification."""
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(cwd),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _unprivileged_preexec():
    """Drop privileges to `operator` (when running as root) and enforce strict rlimits."""
    ids = _operator_ids() if os.geteuid() == 0 else None

    def _fn() -> None:
        import resource

        with _suppress_os():
            resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        with _suppress_os():
            resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        with _suppress_os():
            resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        if ids is not None:
            uid, gid = ids
            os.setgid(gid)
            os.setuid(uid)

    return _fn


# ---------------------------------------------------------------------------
# Real Daemon Bootstrappers (Firecracker MicroVM mode)
# ---------------------------------------------------------------------------

def _start_real_postgres_stack(root: Path, broken: bool) -> None:
    """Boot real PostgreSQL 16 (:5432), PgBouncer (:6432), Redis (:6379) & FastAPI (:8000)."""
    # 1. Start PostgreSQL if not already listening
    if not _port_open(5432):
        # Find installed pg_ctlcluster or postgres binary
        pg_ctlcluster = shutil.which("pg_ctlcluster")
        if pg_ctlcluster:
            ver_dirs = sorted(Path("/etc/postgresql").glob("*"))
            if ver_dirs:
                ver = ver_dirs[-1].name
                # Allow local trust auth so operator can psql without hunting passwords
                hba = Path(f"/etc/postgresql/{ver}/main/pg_hba.conf")
                if hba.exists():
                    hba_text = hba.read_text(encoding="utf-8")
                    if "127.0.0.1/32 trust" not in hba_text:
                        hba.write_text(
                            "local all all trust\n"
                            "host all all 127.0.0.1/32 trust\n"
                            "host all all ::1/128 trust\n",
                            encoding="utf-8",
                        )
                subprocess.run(
                    [pg_ctlcluster, ver, "main", "start"],
                    check=False,
                    capture_output=True,
                )
        _wait_port(5432, timeout_s=12.0)

    # 2. Create operator superuser-less role + orders DB + 12,000 realistic rows
    if _port_open(5432) and psycopg is not None:
        with psycopg.connect("host=127.0.0.1 port=5432 user=postgres dbname=postgres", autocommit=True) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'operator'")
            if cur.fetchone() is None:
                cur.execute("CREATE ROLE operator WITH LOGIN PASSWORD 'crucible'")
            cur.execute("SELECT 1 FROM pg_database WHERE datname = 'orders'")
            if cur.fetchone() is None:
                cur.execute("CREATE DATABASE orders OWNER operator")

        with psycopg.connect("host=127.0.0.1 port=5432 user=operator dbname=orders", autocommit=True) as conn:
            cur = conn.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS orders ("
                "id SERIAL PRIMARY KEY, "
                "tenant_id TEXT NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL, "
                "amount_cents INTEGER NOT NULL, "
                "status TEXT NOT NULL)"
            )
            cur.execute("SELECT COUNT(*) FROM orders")
            row_count = int(cur.fetchone()[0])  # type: ignore[index]
            if row_count < 10000:
                cur.execute("TRUNCATE orders RESTART IDENTITY")
                cur.execute(
                    "INSERT INTO orders (tenant_id, created_at, amount_cents, status) "
                    "SELECT 'tenant_' || lpad((g % 40)::text, 2, '0'), "
                    "       now() - (g || ' minutes')::interval, "
                    "       1500 + ((g * 37) % 18000), "
                    "       CASE WHEN g % 15 = 0 THEN 'refunded' ELSE 'paid' END "
                    "FROM generate_series(1, 15000) AS g"
                )
            cur.execute("DROP INDEX IF EXISTS idx_orders_tenant_created")
            if not broken:
                cur.execute(
                    "CREATE INDEX idx_orders_tenant_created ON orders (tenant_id, created_at DESC)"
                )
            cur.execute("ANALYZE orders")

    # 3. Real PgBouncer (:6432) owned by `operator` so operator can edit & reload live!
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    userlist = root / "config" / "userlist.txt"
    userlist.write_text('"operator" "crucible"\n"postgres" "postgres"\n', encoding="utf-8")
    pool_size = 2 if broken else 32
    pgb_ini = root / "config" / "pgbouncer.ini"
    pgb_ini.write_text(
        f"[databases]\n"
        f"orders = host=127.0.0.1 port=5432 dbname=orders user=operator\n\n"
        f"[pgbouncer]\n"
        f"listen_addr = 127.0.0.1\n"
        f"listen_port = 6432\n"
        f"auth_type = trust\n"
        f"auth_file = {userlist}\n"
        f"admin_users = operator, postgres\n"
        f"stats_users = operator, postgres\n"
        f"pool_mode = transaction\n"
        f"max_client_conn = 500\n"
        f"default_pool_size = {pool_size}\n"
        f"query_wait_timeout = 15\n"
        f"pidfile = {root}/logs/pgbouncer.pid\n"
        f"logfile = {root}/logs/pgbouncer.log\n",
        encoding="utf-8",
    )
    _chown_tree(root)

    # Restart/reload PgBouncer as operator
    subprocess.run(["pkill", "-TERM", "pgbouncer"], check=False, capture_output=True)
    time.sleep(0.15)
    ids = _operator_ids()
    if ids is not None:
        uid, gid = ids
        subprocess.Popen(
            ["pgbouncer", "-d", str(pgb_ini)],
            user=uid,
            group=gid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_port(6432, timeout_s=5.0)

    # 4. Real Redis (:6379)
    if shutil.which("redis-server") and not _port_open(6379):
        subprocess.Popen(
            ["redis-server", "--daemonize", "yes", "--bind", "127.0.0.1", "--port", "6379", "--save", ""],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # 5. Live FastAPI Orders Service (:8000) querying real Postgres through PgBouncer (:6432)
    api_script = root / "app" / "orders_api.py"
    api_script.parent.mkdir(parents=True, exist_ok=True)
    api_script.write_text(
        """from __future__ import annotations
import time
import psycopg
from fastapi import FastAPI

app = FastAPI(title="Crucible Lab1 Orders API")

@app.get("/health")
def health():
    return {"status": "ok", "service": "orders-api"}

@app.get("/api/orders")
def get_orders(tenant_id: str = "tenant_07"):
    t0 = time.perf_counter()
    with psycopg.connect("host=127.0.0.1 port=6432 user=operator dbname=orders") as conn:
        rows = conn.execute(
            "SELECT id, amount_cents, status FROM orders WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 25",
            (tenant_id,),
        ).fetchall()
    ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {"tenant_id": tenant_id, "count": len(rows), "latency_ms": ms, "orders": [{"id": r[0], "amount_cents": r[1], "status": r[2]} for r in rows[:5]]}
""",
        encoding="utf-8",
    )
    if not _port_open(8000):
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "orders_api:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(api_script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_port(8000, timeout_s=5.0)


def _start_real_nginx_stack(root: Path, broken: bool) -> None:
    """Boot real NGINX (:8080 HTTP, :8443 TLS 1.3) + real Uvicorn backend (:8000)."""
    (root / "nginx").mkdir(parents=True, exist_ok=True)
    (root / "nginx" / "certs").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    cert = root / "nginx" / "certs" / "edge.crt"
    key = root / "nginx" / "certs" / "edge.key"
    if not cert.exists() or not key.exists():
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "7",
                "-subj",
                "/CN=edge.crucible.local",
            ],
            check=False,
            capture_output=True,
        )

    # Real FastAPI backend (:8000) with 60s idle timeout
    app_dir = root / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "edge_backend.py").write_text(
        """from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok", "upstream": "edge-api", "idle_timeout_s": 60}
""",
        encoding="utf-8",
    )
    if not _port_open(8000):
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "edge_backend:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--timeout-keep-alive",
                "60",
            ],
            cwd=str(app_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_port(8000, timeout_s=5.0)

    # Main nginx.conf running cleanly under `operator` (non-root ports 8080/8443)
    main_conf = root / "nginx" / "nginx.conf"
    main_conf.write_text(
        f"worker_processes 1;\n"
        f"pid {root}/logs/nginx.pid;\n"
        f"error_log {root}/logs/nginx-error.log warn;\n"
        f"events {{ worker_connections 256; }}\n"
        f"http {{\n"
        f"    access_log {root}/logs/nginx-access.log;\n"
        f"    client_body_temp_path {root}/logs/nginx-body;\n"
        f"    proxy_temp_path {root}/logs/nginx-proxy;\n"
        f"    fastcgi_temp_path {root}/logs/nginx-fastcgi;\n"
        f"    uwsgi_temp_path {root}/logs/nginx-uwsgi;\n"
        f"    scgi_temp_path {root}/logs/nginx-scgi;\n"
        f"    include {root}/nginx/upstream.conf;\n"
        f"    server {{\n"
        f"        listen 127.0.0.1:8080;\n"
        f"        listen 127.0.0.1:8443 ssl;\n"
        f"        ssl_certificate {cert};\n"
        f"        ssl_certificate_key {key};\n"
        f"        ssl_protocols TLSv1.2 TLSv1.3;\n"
        f"        location / {{\n"
        f"            proxy_pass http://fastapi_backend;\n"
        f"            proxy_http_version 1.1;\n"
        f"            proxy_set_header Connection \"\";\n"
        f"            proxy_set_header Host $host;\n"
        f"        }}\n"
        f"    }}\n"
        f"}}\n",
        encoding="utf-8",
    )
    _chown_tree(root)

    subprocess.run(["pkill", "-TERM", "nginx"], check=False, capture_output=True)
    time.sleep(0.15)
    ids = _operator_ids()
    if ids is not None:
        uid, gid = ids
        subprocess.Popen(
            ["nginx", "-c", str(main_conf)],
            user=uid,
            group=gid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_port(8443, timeout_s=5.0)


# ---------------------------------------------------------------------------
# Workspace Seeders (Labs 1-6)
# ---------------------------------------------------------------------------

def _seed_lab1(root: Path, broken: bool) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(parents=True, exist_ok=True)

    real_pg = has_real_postgres()
    if real_pg:
        _start_real_postgres_stack(root, broken=broken)
        _write_executable(
            root / "bin" / "pg-xray",
            "#!/usr/bin/env bash\n"
            "echo '=== LIVE POSTGRES 16 EXPLAIN ANALYZE (15,000 orders) ==='\n"
            "psql -h 127.0.0.1 -p 5432 -U operator -d orders -c "
            "\"EXPLAIN (ANALYZE, BUFFERS) SELECT id, amount_cents FROM orders WHERE tenant_id='tenant_07' ORDER BY created_at DESC LIMIT 25;\"\n"
            "echo ''\n"
            "echo '=== LIVE PGBOUNCER POOLS (:6432) ==='\n"
            "psql -h 127.0.0.1 -p 6432 -U operator -d pgbouncer -c \"SHOW POOLS;\"\n"
            "psql -h 127.0.0.1 -p 6432 -U operator -d pgbouncer -c \"SHOW CONFIG;\" | grep -E 'default_pool_size|pool_mode|max_client_conn'\n"
            "echo ''\n"
            "echo '=== LIVE /api/orders PROBE (:8000) ==='\n"
            "curl -sS 'http://127.0.0.1:8000/api/orders?tenant_id=tenant_07' | jq .\n",
        )
        _write_executable(
            root / "bin" / "reload-pgbouncer",
            f"#!/usr/bin/env bash\n"
            f"set -e\n"
            f"if [ -f {root}/logs/pgbouncer.pid ]; then\n"
            f"  kill -HUP $(cat {root}/logs/pgbouncer.pid) && echo 'PgBouncer reloaded live (SIGHUP)'\n"
            f"else\n"
            f"  pgbouncer -d {root}/config/pgbouncer.ini && echo 'PgBouncer started'\n"
            f"fi\n",
        )
    else:
        # Workspace-lite fallback (macOS / non-root CI)
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
        _write_executable(
            root / "bin" / "pg-xray",
            "#!/usr/bin/env bash\n"
            "echo '=== EXPLAIN QUERY PLAN (data/orders.db) ==='\n"
            "sqlite3 data/orders.db \"EXPLAIN QUERY PLAN SELECT id, amount_cents FROM orders WHERE tenant_id='tenant_07' ORDER BY created_at DESC LIMIT 25;\"\n"
            "echo ''\n"
            "echo '=== PgBouncer Pool Config ==='\n"
            "grep -E 'pool_mode|default_pool_size|max_client_conn' config/pgbouncer.ini\n",
        )

    (root / "logs" / "db.log").write_text(
        (
            "2026-11-25T19:10:01Z WARN slow_query duration_ms=6840 plan='Seq Scan on orders' "
            "sql=\"SELECT * FROM orders WHERE tenant_id='tenant_07' ORDER BY created_at DESC LIMIT 25\"\n"
            "2026-11-25T19:10:02Z ERROR pgbouncer cl_waiting=148 sv_active=2 default_pool_size=2\n"
        )
        if broken
        else "2026-11-25T19:10:01Z INFO query duration_ms=1.8 plan='Index Scan using idx_orders_tenant_created'\n",
        encoding="utf-8",
    )


def _seed_lab2(root: Path, broken: bool) -> None:
    (root / "nginx").mkdir(parents=True, exist_ok=True)
    (root / "deploy").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    ka = 75 if broken else 50
    (root / "nginx" / "upstream.conf").write_text(
        f"upstream fastapi_backend {{\n"
        f"    server 127.0.0.1:8000;\n"
        f"    keepalive 64;\n"
        f"    # Upstream FastAPI/Uvicorn idle timeout is 60s\n"
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
    if has_real_nginx():
        _start_real_nginx_stack(root, broken=broken)
        _write_executable(
            root / "bin" / "reload-nginx",
            f"#!/usr/bin/env bash\n"
            f"set -e\n"
            f"nginx -t -c {root}/nginx/nginx.conf\n"
            f"if [ -f {root}/logs/nginx.pid ]; then\n"
            f"  kill -HUP $(cat {root}/logs/nginx.pid) && echo 'NGINX reloaded cleanly (TLS 1.3 :8443)'\n"
            f"else\n"
            f"  nginx -c {root}/nginx/nginx.conf && echo 'NGINX started'\n"
            f"fi\n",
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
    tid = row.get("tenant_id")
    rev = row.get("revenue_cents", 0)
    if isinstance(tid, str) and tid.strip() and isinstance(rev, (int, float)) and rev >= 0:
        good.append(row)
    else:
        bad.append(row)

curated.write_text("\\n".join(json.dumps(r) for r in good) + ("\\n" if good else ""))
dlq.write_text("\\n".join(json.dumps(r) for r in bad) + ("\\n" if bad else ""))
print(f"Published {len(good)} clean rows, quarantined {len(bad)} invalid rows to dlq.jsonl")
"""
    )
    _write_executable(root / "wap" / "publish_gate.py", gate_code)
    _chown_tree(root)
    subprocess.run(
        [sys.executable, "wap/publish_gate.py"],
        cwd=str(root),
        env=_scrubbed_subprocess_env(root),
        preexec_fn=_unprivileged_preexec(),
        check=False,
        timeout=5,
    )


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
print("PASS: Local ACL smoke check passed (2/2 small_co docs, 0 leaks)")
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
print("PASS: Local fencing smoke check passed")
""",
        encoding="utf-8",
    )


def _seed_lab6(root: Path, broken: bool) -> None:
    (root / "k8s").mkdir(parents=True, exist_ok=True)
    port_block = (
        "      - protocol: TCP\n        port: 443\n      # BUG: PgBouncer port 6432 is blocked!\n"
        if broken
        else "      - protocol: TCP\n        port: 443\n      - protocol: TCP\n        port: 6432\n      - protocol: UDP\n        port: 53\n"
    )
    (root / "k8s" / "networkpolicy.yaml").write_text(
        f"apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: api-egress\nspec:\n"
        f"  podSelector:\n    matchLabels:\n      app: api\n  policyTypes:\n    - Egress\n"
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
    mode_label = (
        "FIRECRACKER KVM MICROVM · REAL PRODUCTION DAEMONS"
        if (has_real_postgres() or has_real_nginx())
        else "ISOLATED LINUX WORKSPACE"
    )
    (root / "README.md").write_text(
        f"# CRUCIBLE LIVE LINUX WAR-ROOM · {template_id}\n"
        f"Sandbox ID: {sandbox_id}\n"
        f"Runtime: {mode_label}\n\n"
        f"## Incident Status\n"
        f"{'P1 BLIND OUTAGE ARMED — ' + fault.symptom if arm_fault else 'NOMINAL BASELINE (Healthy). Trigger Blind Outage to inject fault.'}\n\n"
        f"## Real Commands Available\n"
        f"- Standard Linux tools: ls, cat, grep, sed, awk, psql, sqlite3, nginx, python3, jq, ss, ps, openssl, curl, vim, nano\n"
        f"- Run `hint` for a guided nudge toward the root cause\n"
        f"- Click `Verify SLA & Sign` in the War-Room header (runs immutable root-owned grader)\n",
        encoding="utf-8",
    )

    _write_executable(
        root / "bin" / "hint",
        f"#!/usr/bin/env bash\necho 'REMEDIATION HINT: {fault.remediation_hint}'\n",
    )
    # Note: `check-sla` NEVER imports orchestrator code directly from student shell in Firecracker mode;
    # in Firecracker mode it queries the local read-only status or directs to the signed grader!
    _write_executable(
        root / "bin" / "check-sla",
        "#!/usr/bin/env bash\n"
        "echo '[crucible-grader] Click \"Verify SLA & Sign\" in the War-Room toolbar to run the immutable root-owned grader and mint your SHA-256 receipt.'\n",
    )
    _chown_tree(root)


def arm_scenario_fault(root: Path, template_id: str, sandbox_id: str) -> RealLabFault:
    provision_workspace(root, template_id, sandbox_id, arm_fault=True)
    return LAB_FAULTS[template_id]


# ---------------------------------------------------------------------------
# Immutable Tamper-Proof SLA Verifier (NEVER trusts user test files!)
# ---------------------------------------------------------------------------

def _verify_lab1(root: Path) -> tuple[bool, str]:
    if has_real_postgres() and psycopg is not None:
        # 1. Verify REAL Postgres 16 query plan uses an Index Scan
        try:
            with psycopg.connect("host=127.0.0.1 port=5432 user=operator dbname=orders", connect_timeout=3) as conn:
                plan_json = conn.execute(
                    "EXPLAIN (FORMAT JSON) SELECT id, amount_cents FROM orders "
                    "WHERE tenant_id = 'tenant_07' ORDER BY created_at DESC LIMIT 25"
                ).fetchone()[0]  # type: ignore[index]
        except Exception as exc:
            return False, f"PostgreSQL :5432 unreachable: {exc}"

        plan_str = json.dumps(plan_json)
        if "Seq Scan" in plan_str or ("Index Scan" not in plan_str and "Index Only Scan" not in plan_str):
            return False, "Live PostgreSQL 16 plan still doing Seq Scan on orders; create composite index on (tenant_id, created_at)"

        # 2. Verify REAL PgBouncer live running config (:6432) has default_pool_size >= 25
        live_pool = 0
        try:
            with psycopg.connect("host=127.0.0.1 port=6432 user=operator dbname=pgbouncer", autocommit=True, connect_timeout=3) as conn:
                rows = conn.execute("SHOW CONFIG").fetchall()
                for row in rows:
                    if str(row[0]).strip() == "default_pool_size":
                        live_pool = int(str(row[1]).strip())
                        break
        except Exception as exc:
            return False, f"PgBouncer :6432 admin console unreachable: {exc}"

        if live_pool < 25:
            return False, f"Live PgBouncer (:6432) default_pool_size={live_pool} < 25 (update config/pgbouncer.ini AND run reload-pgbouncer)"

        # 3. Probe live FastAPI Orders service through PgBouncer
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen("http://127.0.0.1:8000/api/orders?tenant_id=tenant_07", timeout=4) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            ms = round((time.perf_counter() - t0) * 1000.0, 1)
            if resp.status != 200 or int(body.get("count", 0)) < 1:
                return False, f"/api/orders returned unexpected response ({resp.status})"
        except Exception as exc:
            return False, f"Live /api/orders probe failed: {exc}"

        return True, f"SLA healthy (LIVE Postgres 16 + PgBouncer): Index Scan active · live default_pool_size={live_pool} · /api/orders {ms}ms"

    # Workspace-lite fallback (SQLite + pgbouncer.ini)
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


def _verify_lab2(root: Path) -> tuple[bool, str]:
    ng_path = root / "nginx" / "upstream.conf"
    dep_path = root / "deploy" / "rollout.yaml"
    if not ng_path.exists() or not dep_path.exists():
        return False, "nginx/upstream.conf or deploy/rollout.yaml missing"
    ng = ng_path.read_text(encoding="utf-8")
    ka = 999
    for line in ng.splitlines():
        s = line.strip()
        if s.startswith("keepalive_timeout"):
            parts = s.split()
            if len(parts) >= 2:
                raw = parts[1].rstrip("s;")
                if raw.isdigit():
                    ka = int(raw)
    if ka > 55:
        return False, f"nginx keepalive_timeout={ka}s exceeds safe threshold (<= 55s < 60s app idle)"

    # Structural YAML validation of preStop drain hook
    dep_raw = dep_path.read_text(encoding="utf-8")
    if yaml is not None:
        try:
            doc = yaml.safe_load(dep_raw)
            containers = doc["spec"]["template"]["spec"]["containers"]
            has_prestop = any(
                isinstance(c, dict)
                and isinstance(c.get("lifecycle"), dict)
                and isinstance(c["lifecycle"].get("preStop"), dict)
                and bool(c["lifecycle"]["preStop"].get("exec") or c["lifecycle"]["preStop"].get("httpGet"))
                for c in containers
            )
            if not has_prestop:
                return False, "deploy/rollout.yaml containers[*].lifecycle.preStop hook missing or invalid"
        except Exception as exc:
            return False, f"deploy/rollout.yaml invalid YAML: {exc}"
    elif "preStop" not in dep_raw:
        return False, "deploy/rollout.yaml is still missing a preStop drain hook"

    if has_real_nginx():
        # Verify real nginx -t AND live TLS :8443 proxy response!
        chk = subprocess.run(
            ["nginx", "-t", "-c", str(root / "nginx" / "nginx.conf")],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if chk.returncode != 0:
            return False, f"nginx -t syntax check failed: {(chk.stderr or chk.stdout).strip()}"
        curl_chk = subprocess.run(
            ["curl", "-skf", "https://127.0.0.1:8443/health"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if curl_chk.returncode != 0 or "edge-api" not in curl_chk.stdout:
            return False, "Live NGINX TLS :8443 -> Uvicorn :8000 health check failed (run reload-nginx)"
        return True, f"SLA healthy (LIVE NGINX TLS 1.3): nginx -t OK · keepalive_timeout={ka}s · https://:8443 200 OK · preStop verified"

    return True, f"SLA healthy: keepalive_timeout={ka}s and preStop drain hook active"


def _verify_lab3(root: Path) -> tuple[bool, str]:
    gate = root / "wap" / "publish_gate.py"
    if not gate.exists():
        return False, "wap/publish_gate.py missing"

    # Run user's publish_gate.py against a HIDDEN root-owned adversarial batch in an isolated temp dir!
    hidden_batch = [
        {"event_id": "h_1", "tenant_id": "alpha", "revenue_cents": 1200},
        {"event_id": "h_2", "tenant_id": None, "revenue_cents": 5000},
        {"event_id": "h_3", "tenant_id": "   ", "revenue_cents": 3200},
        {"event_id": "h_4", "tenant_id": "beta", "revenue_cents": 8900},
        {"event_id": "h_5", "revenue_cents": 4100},  # missing tenant_id key completely
        {"event_id": "h_6", "tenant_id": "gamma", "revenue_cents": 2500},
    ]
    with tempfile.TemporaryDirectory(prefix="crucible-grade-lab3-") as td:
        td_path = Path(td)
        (td_path / "wap").mkdir(parents=True, exist_ok=True)
        shutil.copy2(gate, td_path / "wap" / "publish_gate.py")
        (td_path / "wap" / "staging_batch.jsonl").write_text(
            "\n".join(json.dumps(r) for r in hidden_batch) + "\n", encoding="utf-8"
        )
        _chown_tree(td_path)
        proc = subprocess.run(
            [sys.executable, "wap/publish_gate.py"],
            cwd=str(td_path),
            env=_scrubbed_subprocess_env(td_path),
            preexec_fn=_unprivileged_preexec(),
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode != 0:
            return False, f"publish_gate.py failed on hidden audit batch: {(proc.stderr or proc.stdout).strip()[:200]}"
        curated_path = td_path / "wap" / "curated.jsonl"
        dlq_path = td_path / "wap" / "dlq.jsonl"
        if not curated_path.exists() or not dlq_path.exists():
            return False, "publish_gate.py did not produce wap/curated.jsonl and wap/dlq.jsonl"
        curated = [json.loads(l) for l in curated_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        dlq = [json.loads(l) for l in dlq_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if any(not (isinstance(r.get("tenant_id"), str) and r["tenant_id"].strip()) for r in curated):
            return False, "Hidden audit failed: curated.jsonl contains invalid/null/blank tenant_id rows!"
        if len(curated) != 3 or len(dlq) != 3:
            return False, f"Hidden audit failed: expected 3 curated + 3 quarantined DLQ rows, got curated={len(curated)} dlq={len(dlq)}"
    return True, "SLA healthy: WAP gate passed hidden 6-row adversarial audit (3 clean published, 3 poisoned quarantined)"


def _verify_lab4(root: Path) -> tuple[bool, str]:
    retriever = root / "rag" / "retriever.py"
    policy_path = root / "mcp" / "policy.json"
    if not retriever.exists() or not policy_path.exists():
        return False, "rag/retriever.py or mcp/policy.json missing"

    # IMMUTABLE hidden red-team ACL grader (completely ignores user-editable rag/test_acl.py!)
    hidden_test = """
import sys
sys.path.insert(0, "rag")
from retriever import retrieve_for_tenant

CORPUS = [
    {"id": "x1", "tenant_id": "whale_corp", "score": 0.999, "text": "Whale M&A"},
    {"id": "x2", "tenant_id": "whale_corp", "score": 0.995, "text": "Whale Payroll"},
    {"id": "x3", "tenant_id": "whale_corp", "score": 0.991, "text": "Whale Keys"},
    {"id": "s1", "tenant_id": "startup_z", "score": 0.61, "text": "Startup Runbook 1"},
    {"id": "s2", "tenant_id": "startup_z", "score": 0.58, "text": "Startup Runbook 2"},
    {"id": "s3", "tenant_id": "startup_z", "score": 0.42, "text": "Startup Runbook 3"},
]
res = retrieve_for_tenant(CORPUS, tenant_id="startup_z", top_k=2)
assert isinstance(res, list) and len(res) == 2, f"Post-filter starvation: expected 2 startup_z docs, got {len(res)}"
assert all(d["tenant_id"] == "startup_z" for d in res), "CRITICAL: cross-tenant document leaked!"
assert [d["id"] for d in res] == ["s1", "s2"], f"Incorrect score ordering: {[d['id'] for d in res]}"
empty = retrieve_for_tenant(CORPUS, tenant_id="ghost_tenant", top_k=2)
assert empty == [], f"Unauthorized tenant received docs: {empty}"
print("HIDDEN_ACL_PASS")
"""
    proc = subprocess.run(
        [sys.executable, "-c", hidden_test],
        cwd=str(root),
        env=_scrubbed_subprocess_env(root),
        preexec_fn=_unprivileged_preexec(),
        capture_output=True,
        text=True,
        timeout=8,
    )
    if proc.returncode != 0 or "HIDDEN_ACL_PASS" not in proc.stdout:
        return False, f"Hidden ACL red-team probe failed: {(proc.stderr or proc.stdout).strip()[:220]}"

    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return False, f"mcp/policy.json invalid JSON: {exc}"
    if float(policy.get("max_usd", 999)) > 2.0 or int(policy.get("max_steps", 999)) > 12:
        return False, f"mcp/policy.json caps unsafe: max_usd={policy.get('max_usd')} max_steps={policy.get('max_steps')}"
    if policy.get("require_approval_for_writes") is not True:
        return False, "mcp/policy.json must enforce require_approval_for_writes: true"
    return True, "SLA healthy: hidden multi-tenant pre-filter ACL passed (0 leaks) + bounded MCP budget verified"


def _verify_lab5(root: Path) -> tuple[bool, str]:
    guard = root / "raft" / "storage_guard.py"
    if not guard.exists():
        return False, "raft/storage_guard.py missing"

    # IMMUTABLE hidden adversarial split-brain grader (ignores user-editable raft/test_fencing.py!)
    hidden_test = """
import sys
sys.path.insert(0, "raft")
from storage_guard import FencedStorage

s = FencedStorage()
assert s.write("acct", "100", fencing_token=10) is True, "Initial term-10 write failed"
assert s.write("acct", "250", fencing_token=15) is True, "Higher term-15 write failed"
assert s.write("acct", "STALE_14", fencing_token=14) is False, "Zombie leader term=14 was accepted!"
assert s.write("acct", "STALE_01", fencing_token=1) is False, "Ancient leader term=1 was accepted!"
assert s.data["acct"] == "250", f"Committed state corrupted: {s.data['acct']}"
assert s.write("acct", "300", fencing_token=15) is True, "Same-term leader write should succeed"
assert s.write("acct", "400", fencing_token=16) is True, "New term-16 leader write failed"
assert s.write("acct", "STALE_15", fencing_token=15) is False, "Old term-15 zombie write after term-16 was accepted!"
assert s.data["acct"] == "400"
print("HIDDEN_RAFT_PASS")
"""
    proc = subprocess.run(
        [sys.executable, "-c", hidden_test],
        cwd=str(root),
        env=_scrubbed_subprocess_env(root),
        preexec_fn=_unprivileged_preexec(),
        capture_output=True,
        text=True,
        timeout=8,
    )
    if proc.returncode != 0 or "HIDDEN_RAFT_PASS" not in proc.stdout:
        return False, f"Hidden Raft fencing probe failed: {(proc.stderr or proc.stdout).strip()[:220]}"
    return True, "SLA healthy: hidden multi-term split-brain adversarial suite passed (0 zombie overwrites)"


def _verify_lab6(root: Path) -> tuple[bool, str]:
    np_path = root / "k8s" / "networkpolicy.yaml"
    pdb_path = root / "k8s" / "pdb.yaml"
    if not np_path.exists() or not pdb_path.exists():
        return False, "k8s/networkpolicy.yaml or k8s/pdb.yaml missing"

    np_text = np_path.read_text(encoding="utf-8")
    pdb_text = pdb_path.read_text(encoding="utf-8")

    if yaml is not None:
        try:
            np_doc = yaml.safe_load(np_text)
            pdb_doc = yaml.safe_load(pdb_text)
        except Exception as exc:
            return False, f"Invalid K8s YAML manifest: {exc}"
        if not isinstance(np_doc, dict) or np_doc.get("kind") != "NetworkPolicy":
            return False, "k8s/networkpolicy.yaml must be kind: NetworkPolicy"
        policy_types = np_doc.get("spec", {}).get("policyTypes", [])
        if "Egress" not in policy_types:
            return False, "NetworkPolicy spec.policyTypes must include Egress"
        egress = np_doc.get("spec", {}).get("egress", []) or []
        ports_found: set[tuple[str, int]] = set()
        for rule in egress:
            if not isinstance(rule, dict):
                continue
            for p in rule.get("ports", []) or []:
                if isinstance(p, dict) and p.get("port") is not None:
                    proto = str(p.get("protocol", "TCP")).upper()
                    try:
                        ports_found.add((proto, int(p["port"])))
                    except (ValueError, TypeError):
                        pass
        if ("TCP", 6432) not in ports_found:
            return False, "k8s/networkpolicy.yaml egress still blocks TCP port 6432 to PgBouncer"

        if not isinstance(pdb_doc, dict) or pdb_doc.get("kind") != "PodDisruptionBudget":
            return False, "k8s/pdb.yaml must be kind: PodDisruptionBudget"
        pdb_spec = pdb_doc.get("spec", {}) or {}
        min_avail = pdb_spec.get("minAvailable")
        max_unavail = pdb_spec.get("maxUnavailable")
        safe_pdb = False
        if max_unavail is not None:
            try:
                safe_pdb = int(str(max_unavail).rstrip("%")) >= 1
            except ValueError:
                safe_pdb = False
        elif min_avail is not None:
            raw = str(min_avail).strip()
            if raw.endswith("%"):
                try:
                    safe_pdb = int(raw[:-1]) <= 80
                except ValueError:
                    safe_pdb = False
            else:
                try:
                    safe_pdb = int(raw) <= 3
                except ValueError:
                    safe_pdb = False
        if not safe_pdb:
            return False, f"k8s/pdb.yaml blocks AZ node drains (minAvailable={min_avail}, maxUnavailable={max_unavail}; need <= 80% or maxUnavailable >= 1)"
        return True, "SLA healthy: structural K8s NetworkPolicy allows TCP:6432 egress & PDB permits safe AZ drains"

    # Fallback if PyYAML unavailable
    if "6432" not in np_text:
        return False, "k8s/networkpolicy.yaml still blocks egress TCP port 6432 to PgBouncer"
    if "100%" in pdb_text:
        return False, "k8s/pdb.yaml minAvailable: 100% still blocks AZ node drains"
    return True, "SLA healthy: Cilium/K8s egress allows :6432 and PDB allows safe node drains"


def verify_workspace_sla(root: Path, template_id: str) -> tuple[bool, str]:
    if not root.exists():
        return False, "sandbox workspace missing"
    verifiers = {
        "lab1-core-engine": _verify_lab1,
        "lab2-linux-tls": _verify_lab2,
        "lab3-lakehouse-wap": _verify_lab3,
        "lab4-rag-acl": _verify_lab4,
        "lab5-raft-internals": _verify_lab5,
        "lab6-k8s-ebpf": _verify_lab6,
    }
    fn = verifiers.get(template_id)
    if fn is None:
        return False, f"unknown template {template_id}"
    return fn(root)


def collect_live_daemons() -> dict[str, bool]:
    return {
        "postgresql": _port_open(5432),
        "pgbouncer": _port_open(6432),
        "redis": _port_open(6379),
        "nginx_tls": _port_open(8443),
        "app_api": _port_open(8000),
    }
