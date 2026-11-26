"""Tamper-proof Crucible Lab Provisioner, Real Daemon Manager, File Guard & Immutable SLA Grader.

Designed to live under `/opt/crucible-grader` (root:root 0700) inside each hardware-isolated
Firecracker MicroVM so the unprivileged `operator` shell user cannot read or alter grading logic,
hidden test datasets, or service verification probes.
"""
from __future__ import annotations

import json
import os
import pwd
import re
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


try:
    from build_projects import (  # type: ignore[import-not-found]
        list_build_projects,
        run_project_stage_tests,
        scaffold_project_workspace,
    )
except ImportError:
    from orchestrator.build_projects import (
        list_build_projects,
        run_project_stage_tests,
        scaffold_project_workspace,
    )

try:
    from scenarios_expanded import (  # type: ignore[import-not-found]
        LAB_SCENARIO_CATALOG,
        get_scenario_spec,
        list_all_scenarios,
        seed_lab7,
        seed_lab8,
        seed_lab9,
        seed_lab10,
        verify_lab7,
        verify_lab8,
        verify_lab9,
        verify_lab10,
    )
except ImportError:
    from orchestrator.scenarios_expanded import (
        LAB_SCENARIO_CATALOG,
        get_scenario_spec,
        list_all_scenarios,
        seed_lab7,
        seed_lab8,
        seed_lab9,
        seed_lab10,
        verify_lab7,
        verify_lab8,
        verify_lab9,
        verify_lab10,
    )


@dataclass(frozen=True)
class RealLabFault:
    fault_id: str
    symptom: str
    remediation_hint: str


LAB_FAULTS: dict[str, RealLabFault] = {
    tpl_id: RealLabFault(
        fault_id=specs[0].scenario_id,
        symptom=specs[0].symptom,
        remediation_hint=specs[0].remediation_hint,
    )
    for tpl_id, specs in LAB_SCENARIO_CATALOG.items()
}

ALLOWED_TEXT_EXTS = {
    ".ini", ".conf", ".yaml", ".yml", ".py", ".json", ".jsonl", ".md", ".log", ".txt", ".sh", ".sql",
}
MAX_EDIT_BYTES = 256 * 1024


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


class _suppress_os:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, _exc: Any, _tb: Any) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)


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
    return {
        "PATH": f"{cwd / 'bin'}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(cwd),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _unprivileged_preexec():
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
# Safe Workspace File Explorer & Live Editor Helpers (Strict Path Containment)
# ---------------------------------------------------------------------------

def _resolve_safe_workspace_path(root: Path, rel_path: str) -> Path:
    clean = rel_path.strip().lstrip("/")
    if not clean or ".." in Path(clean).parts or "\x00" in clean:
        raise ValueError("Invalid workspace file path")
    root_resolved = root.resolve()
    target = (root_resolved / clean).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Path escapes sandbox workspace") from exc
    if target.is_dir():
        raise ValueError("Target is a directory")
    if target.suffix.lower() not in ALLOWED_TEXT_EXTS:
        raise ValueError(f"Editing '{target.suffix or 'binary'}' files is not permitted via file editor")
    return target


def list_editable_files(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    root_resolved = root.resolve()
    items: list[dict[str, Any]] = []
    skip_dirs = {"bin", "certs", "__pycache__", ".cache"}
    for cur_root, dirs, files in os.walk(root_resolved):
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs and not d.startswith("."))
        for fname in sorted(files):
            if fname.startswith(".") or fname.endswith(".pid") or fname.endswith(".key") or fname.endswith(".crt"):
                continue
            fpath = Path(cur_root) / fname
            if fpath.suffix.lower() not in ALLOWED_TEXT_EXTS:
                continue
            try:
                rel = fpath.relative_to(root_resolved).as_posix()
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > MAX_EDIT_BYTES:
                continue
            readonly = rel.startswith("logs/") or rel == "README.md" or rel.endswith("userlist.txt")
            items.append(
                {
                    "path": rel,
                    "size": size,
                    "ext": fpath.suffix.lower().lstrip("."),
                    "readonly": readonly,
                }
            )
    # Prioritize primary editable config/code files first
    items.sort(key=lambda x: (1 if x["readonly"] else 0, 1 if x["path"].startswith("app/") else 0, x["path"]))
    return items


def read_workspace_file(root: Path, rel_path: str) -> dict[str, Any]:
    target = _resolve_safe_workspace_path(root, rel_path)
    if not target.exists():
        raise FileNotFoundError(f"File '{rel_path}' not found")
    data = target.read_bytes()
    if len(data) > MAX_EDIT_BYTES:
        raise ValueError("File exceeds 256 KB editor limit")
    rel = target.relative_to(root.resolve()).as_posix()
    return {
        "path": rel,
        "content": data.decode("utf-8", errors="replace"),
        "size": len(data),
        "readonly": rel.startswith("logs/") or rel == "README.md" or rel.endswith("userlist.txt"),
    }


def write_workspace_file(root: Path, rel_path: str, content: str) -> dict[str, Any]:
    target = _resolve_safe_workspace_path(root, rel_path)
    rel = target.relative_to(root.resolve()).as_posix()
    if rel.startswith("logs/") or rel == "README.md" or rel.endswith("userlist.txt"):
        raise ValueError(f"File '{rel}' is read-only")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_EDIT_BYTES:
        raise ValueError("File exceeds 256 KB editor limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded)
    ids = _operator_ids()
    if os.geteuid() == 0 and ids is not None:
        with _suppress_os():
            os.chown(target, ids[0], ids[1])
    return {"path": rel, "size": len(encoded), "saved": True}


def reload_lab_daemon(root: Path, template_id: str) -> dict[str, Any]:
    """Safely reload the active lab's live daemon or re-run its pipeline as `operator`."""
    cmd: list[str] | None = None
    if template_id == "lab1-core-engine" and (root / "bin" / "reload-pgbouncer").exists():
        cmd = [str(root / "bin" / "reload-pgbouncer")]
    elif template_id == "lab2-linux-tls" and (root / "bin" / "reload-nginx").exists():
        cmd = [str(root / "bin" / "reload-nginx")]
    elif template_id == "lab11-p0-capstone":
        outs = []
        for script_name in ("reload-pgbouncer", "reload-nginx"):
            sp = root / "bin" / script_name
            if sp.exists():
                p = subprocess.run(
                    [str(sp)],
                    cwd=str(root),
                    env=_scrubbed_subprocess_env(root),
                    preexec_fn=_unprivileged_preexec(),
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                outs.append((p.stdout + " " + p.stderr).strip())
        if outs:
            return {"reloaded": True, "exit_code": 0, "output": " | ".join(outs)[:400]}
    elif template_id == "lab3-lakehouse-wap" and (root / "wap" / "publish_gate.py").exists():
        cmd = [sys.executable, "wap/publish_gate.py"]

    if cmd is None:
        return {"reloaded": False, "output": "Config saved (no daemon reload required for this lab)."}

    proc = subprocess.run(
        cmd,
        cwd=str(root),
        env=_scrubbed_subprocess_env(root),
        preexec_fn=_unprivileged_preexec(),
        capture_output=True,
        text=True,
        timeout=8,
    )
    out = (proc.stdout + "\n" + proc.stderr).strip()
    return {
        "reloaded": proc.returncode == 0,
        "exit_code": proc.returncode,
        "output": out[:400] or ("Reloaded successfully." if proc.returncode == 0 else "Reload failed."),
    }


# ---------------------------------------------------------------------------
# Real Daemon Bootstrappers (Firecracker MicroVM mode)
# ---------------------------------------------------------------------------

def _start_real_postgres_stack(root: Path, broken: bool) -> None:
    if not _port_open(5432):
        pg_ctlcluster = shutil.which("pg_ctlcluster")
        if pg_ctlcluster:
            ver_dirs = sorted(Path("/etc/postgresql").glob("*"))
            if ver_dirs:
                ver = ver_dirs[-1].name
                hba = Path(f"/etc/postgresql/{ver}/main/pg_hba.conf")
                if hba.exists():
                    hba_text = hba.read_text(encoding="utf-8")
                    if "host orders operator 127.0.0.1/32 trust" not in hba_text:
                        # Security: postgres superuser is restricted to local peer auth only;
                        # TCP access is strictly scoped to unprivileged `operator` role on `orders`.
                        hba.write_text(
                            "local all postgres peer\n"
                            "local all operator trust\n"
                            "host orders operator 127.0.0.1/32 trust\n"
                            "host orders operator ::1/128 trust\n",
                            encoding="utf-8",
                        )
                subprocess.run([pg_ctlcluster, ver, "main", "start"], check=False, capture_output=True)
        _wait_port(5432, timeout_s=12.0)

    if _port_open(5432) and psycopg is not None:
        # Bootstrap roles/db as postgres via local unix socket (piped over stdin — zero bash $$ expansion!)
        pg_bootstrap_sql = (
            "DO $crucible$\n"
            "BEGIN\n"
            "  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operator') THEN\n"
            "    CREATE ROLE operator WITH LOGIN PASSWORD 'crucible';\n"
            "  END IF;\n"
            "END\n"
            "$crucible$;\n"
        )
        if os.geteuid() == 0 and (shutil.which("runuser") or shutil.which("su")):
            pg_cmd = (
                ["runuser", "-u", "postgres", "--", "psql", "-v", "ON_ERROR_STOP=1"]
                if shutil.which("runuser")
                else ["su", "-", "postgres", "-c", "psql -v ON_ERROR_STOP=1"]
            )
            subprocess.run(
                pg_cmd,
                input=pg_bootstrap_sql,
                text=True,
                check=False,
                capture_output=True,
            )
            db_check_cmd = (
                ["runuser", "-u", "postgres", "--", "psql", "-tAc", "SELECT 1 FROM pg_database WHERE datname = 'orders'"]
                if shutil.which("runuser")
                else ["su", "-", "postgres", "-c", "psql -tAc \"SELECT 1 FROM pg_database WHERE datname = 'orders'\""]
            )
            chk = subprocess.run(db_check_cmd, text=True, check=False, capture_output=True)
            if "1" not in (chk.stdout or ""):
                createdb_cmd = (
                    ["runuser", "-u", "postgres", "--", "createdb", "-O", "operator", "orders"]
                    if shutil.which("runuser")
                    else ["su", "-", "postgres", "-c", "createdb -O operator orders"]
                )
                subprocess.run(createdb_cmd, check=False, capture_output=True)
            ext_cmd = (
                ["runuser", "-u", "postgres", "--", "psql", "-d", "orders", "-c", "CREATE EXTENSION IF NOT EXISTS vector;"]
                if shutil.which("runuser")
                else ["su", "-", "postgres", "-c", "psql -d orders -c 'CREATE EXTENSION IF NOT EXISTS vector;'"]
            )
            subprocess.run(ext_cmd, check=False, capture_output=True)
        else:
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

    if shutil.which("redis-server") and not _port_open(6379):
        redis_kwargs: dict[str, Any] = {
            "cwd": "/tmp",
            "env": _scrubbed_subprocess_env(root),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if ids is not None:
            redis_kwargs["user"] = ids[0]
            redis_kwargs["group"] = ids[1]
        subprocess.Popen(
            [
                "redis-server",
                "--daemonize",
                "yes",
                "--dir",
                "/tmp",
                "--pidfile",
                "/tmp/crucible-redis.pid",
                "--logfile",
                "/tmp/crucible-redis.log",
                "--bind",
                "127.0.0.1",
                "--port",
                "6379",
                "--save",
                "",
            ],
            **redis_kwargs,
        )
        _wait_port(6379, timeout_s=4.0)

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
    return {"status": "ok", "service": "orders-api", "upstream": "edge-api", "idle_timeout_s": 60}

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
        api_kwargs: dict[str, Any] = {
            "cwd": str(api_script.parent),
            "env": _scrubbed_subprocess_env(root),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if ids is not None:
            api_kwargs["user"] = ids[0]
            api_kwargs["group"] = ids[1]
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "orders_api:app", "--host", "127.0.0.1", "--port", "8000"],
            **api_kwargs,
        )
        _wait_port(8000, timeout_s=5.0)


def _start_real_nginx_stack(root: Path, broken: bool) -> None:
    (root / "nginx").mkdir(parents=True, exist_ok=True)
    (root / "nginx" / "certs").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    cert = root / "nginx" / "certs" / "edge.crt"
    key = root / "nginx" / "certs" / "edge.key"
    if not cert.exists() or not key.exists():
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert), "-days", "7",
                "-subj", "/CN=edge.crucible.local",
            ],
            check=False,
            capture_output=True,
        )

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
        edge_ids = _operator_ids()
        edge_kwargs: dict[str, Any] = {
            "cwd": str(app_dir),
            "env": _scrubbed_subprocess_env(root),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if edge_ids is not None:
            edge_kwargs["user"] = edge_ids[0]
            edge_kwargs["group"] = edge_ids[1]
        subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "edge_backend:app",
                "--host", "127.0.0.1", "--port", "8000", "--timeout-keep-alive", "60",
            ],
            **edge_kwargs,
        )
        _wait_port(8000, timeout_s=5.0)

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

    if has_real_postgres():
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
            f"export PATH=\"/usr/sbin:/sbin:/usr/local/bin:/usr/bin:/bin\"\n"
            f"if [ -f {root}/logs/pgbouncer.pid ]; then\n"
            f"  kill -HUP $(cat {root}/logs/pgbouncer.pid) && echo 'PgBouncer reloaded live (SIGHUP)'\n"
            f"else\n"
            f"  pgbouncer -d {root}/config/pgbouncer.ini && echo 'PgBouncer started'\n"
            f"fi\n",
        )
    else:
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
            f"export PATH=\"/usr/sbin:/sbin:/usr/local/bin:/usr/bin:/bin\"\n"
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

    # Real DuckDB + Parquet Point-in-Time ML Leakage & WAP Audit script (runs on real DuckDB inside KVM v5!)
    duckdb_join_sql = (
        """-- BUG: regular JOIN pulls future carrier_events (event_ts > pred_ts), leaking future labels!
SELECT s.shipment_id, e.status, e.event_ts <= s.pred_ts AS pit_safe
FROM shipments s
JOIN carrier_events e
  ON s.shipment_id = e.shipment_id
ORDER BY s.shipment_id, e.event_ts DESC"""
        if broken
        else """-- SAFE Point-in-Time ASOF join guarantees zero future leakage (event_ts <= pred_ts)
SELECT s.shipment_id, e.status, e.event_ts <= s.pred_ts AS pit_safe
FROM shipments s
ASOF JOIN carrier_events e
  ON s.shipment_id = e.shipment_id AND s.pred_ts >= e.event_ts
ORDER BY s.shipment_id"""
    )
    duckdb_script = f"""#!/usr/bin/env python3
import duckdb

con = duckdb.connect()
con.execute(\"\"\"
CREATE TABLE shipments AS SELECT * FROM (VALUES
  ('s1', TIMESTAMP '2026-11-20 08:00:00', 1),
  ('s2', TIMESTAMP '2026-11-20 09:00:00', 0)
) t(shipment_id, pred_ts, delayed);
CREATE TABLE carrier_events AS SELECT * FROM (VALUES
  ('s1', TIMESTAMP '2026-11-20 07:30:00', 'in_transit'),
  ('s1', TIMESTAMP '2026-11-21 14:00:00', 'delivered_late'),
  ('s2', TIMESTAMP '2026-11-20 08:45:00', 'in_transit')
) t(shipment_id, event_ts, status);
\"\"\")
rows = con.execute(\"\"\"
{duckdb_join_sql}
\"\"\").fetchall()
assert len(rows) == 2, f"Expected 2 point-in-time rows, got {{len(rows)}}: {{rows}}"
assert all(r[2] for r in rows), f"Temporal leakage detected (future event_ts > pred_ts): {{rows}}"
print(f"DUCKDB_PIT_PASS: {{len(rows)}} shipments verified with zero future leakage -> {{rows}}")
"""
    _write_executable(root / "wap" / "duckdb_pit_audit.py", duckdb_script)
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

    # Real PostgreSQL pgvector HNSW + Pre-Filter Tenant ACL SQL lab script (runs on live Postgres + pgvector inside KVM v5!)
    if has_real_postgres() and not _port_open(5432):
        _start_real_postgres_stack(root, broken=False)

    pgvec_query = (
        """-- BUG: Post-filter slices LIMIT 2 BEFORE filtering tenant_id -> starves small_co (0 rows)!
SELECT id, tenant_id, body, cosine_dist
FROM (
  SELECT id, tenant_id, body, round((embedding <=> '[1,0,0]')::numeric, 4) AS cosine_dist
  FROM rag_chunks
  ORDER BY embedding <=> '[1,0,0]'
  LIMIT 2
) sub
WHERE tenant_id = 'small_co';"""
        if broken
        else """-- SAFE PRE-FILTER: WHERE tenant_id = JWT BEFORE vector distance ORDER BY + LIMIT 2
SELECT id, tenant_id, body, round((embedding <=> '[1,0,0]')::numeric, 4) AS cosine_dist
FROM rag_chunks
WHERE tenant_id = 'small_co'
ORDER BY embedding <=> '[1,0,0]'
LIMIT 2;"""
    )
    (root / "rag" / "pgvector_acl_lab.sql").write_text(
        f"""-- Real PostgreSQL 15 + pgvector Pre-Filter vs Post-Filter Tenant ACL Proof
CREATE EXTENSION IF NOT EXISTS vector;
DROP TABLE IF EXISTS rag_chunks;
CREATE TABLE rag_chunks (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  body text NOT NULL,
  embedding vector(3) NOT NULL
);
CREATE INDEX idx_rag_chunks_tenant ON rag_chunks (tenant_id);
INSERT INTO rag_chunks VALUES
  ('d1', 'mega_corp', 'MegaCorp confidential M&A memo', '[0.99, 0.01, 0.00]'),
  ('d2', 'mega_corp', 'MegaCorp Q4 board deck', '[0.96, 0.04, 0.00]'),
  ('d3', 'small_co',  'SmallCo incident runbook A', '[0.82, 0.18, 0.00]'),
  ('d4', 'small_co',  'SmallCo incident runbook B', '[0.78, 0.22, 0.00]');

{pgvec_query}
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


def _seed_lab0_free_range(root: Path, broken: bool) -> None:
    """Free-Range Enterprise Cloud Range: ALL live daemons healthy + Polyglot Server-Lifecycle starter kit."""
    _seed_lab1(root, broken=broken)
    _seed_lab2(root, broken=broken)
    pg_dir = root / "playground"
    sl_dir = pg_dir / "server-lifecycle"
    sl_dir.mkdir(parents=True, exist_ok=True)
    (pg_dir / "sandbox_notes.md").write_text(
        "# Free-Range Enterprise Cloud Range (Crucible Firecracker KVM)\n\n"
        "Break anything, install Python/Node SDKs (`uv`, `npm`), run real OpenTofu/Prometheus/age/PostgreSQL/Redis/NGINX/Caddy drills, save Checkpoints, or 1-Click Reset anytime!\n\n"
        "## Live Daemons Running Right Now\n"
        "- PostgreSQL 15 (+ pgvector): `psql -h 127.0.0.1 -p 5432 -U operator -d orders`\n"
        "- PgBouncer Pooler: `psql -h 127.0.0.1 -p 6432 -U operator -d orders`\n"
        "- Redis 7: `redis-cli ping`\n"
        "- NGINX TLS 1.3: `curl -k https://127.0.0.1:8443/health`\n"
        "- FastAPI Orders API: `curl http://127.0.0.1:8000/health`\n\n"
        "## Pre-Installed Open-Source Cloud & SRE Arsenal\n"
        "- Python + `uv`: `uv venv ~/myenv && uv pip install --python ~/myenv httpx fastapi`\n"
        "- Node.js + `npm`: `node -v && npm -v`\n"
        "- OpenTofu (Terraform): `cd ~/playground/server-lifecycle && tofu init && tofu plan && tofu apply -auto-approve`\n"
        "- Prometheus + `promtool`: `promtool test rules ~/playground/server-lifecycle/alerts.test.yml`\n"
        "- Encrypted Backup/Restore (`age`): `bash ~/playground/server-lifecycle/backup_restore_drill.sh`\n"
        "- Kubernetes CLI: `kubectl version --client`\n"
        "- Load & Kernel SRE: `wrk -t2 -c10 -d5s http://127.0.0.1:8000/health`, `caddy version`, `strace`, `tcpdump`, `htop`, `rg`\n"
        "- Persistent 2 GB Disk (when enabled): save files in `~/persist/` to keep them across VM sessions!\n",
        encoding="utf-8",
    )
    (pg_dir / "experiment.py").write_text(
        '"""Free-range Python starter script. Edit and run: python3 playground/experiment.py"""\n'
        "import os\n\n"
        "if __name__ == '__main__':\n"
        "    print('Crucible Free-Range Cloud VM ready! CWD:', os.getcwd())\n",
        encoding="utf-8",
    )
    (sl_dir / "main.tf").write_text(
        'terraform {\n'
        '  required_version = ">= 1.4, < 2.0"\n'
        '}\n\n'
        'variable "release" {\n'
        '  type    = string\n'
        '  default = "crucible-release-A"\n'
        '}\n\n'
        'resource "terraform_data" "release" {\n'
        '  input = {\n'
        '    owner        = "crucible-free-range"\n'
        '    release      = var.release\n'
        '    service_kind = "server-lifecycle-lab"\n'
        '  }\n'
        '}\n\n'
        'output "release_record" {\n'
        '  value = terraform_data.release.output\n'
        '}\n',
        encoding="utf-8",
    )
    (sl_dir / "alerts.yml").write_text(
        "groups:\n"
        "  - name: server-lifecycle\n"
        "    rules:\n"
        "      - alert: APIUnavailable\n"
        '        expr: up{job="crucible"} == 0\n'
        "        for: 2m\n"
        "        labels: {severity: critical}\n"
        '        annotations: {summary: "API scrape failed; check process and database"}\n'
        "      - alert: QueueStalled\n"
        "        expr: server_oldest_queued_seconds > 120\n"
        "        for: 2m\n"
        "        labels: {severity: warning}\n"
        '        annotations: {summary: "Oldest queued job exceeds 120s; inspect worker"}\n',
        encoding="utf-8",
    )
    (sl_dir / "alerts.test.yml").write_text(
        "rule_files: [alerts.yml]\n"
        "evaluation_interval: 1m\n"
        "tests:\n"
        "  - interval: 1m\n"
        "    input_series:\n"
        '      - series: \'up{job="crucible"}\'\n'
        "        values: '1 0 0 0 1 1'\n"
        "      - series: 'server_oldest_queued_seconds'\n"
        "        values: '0 130 190 250 0 0'\n"
        "    alert_rule_test:\n"
        "      - eval_time: 3m\n"
        "        alertname: APIUnavailable\n"
        "        exp_alerts:\n"
        "          - exp_labels: {job: crucible, severity: critical}\n"
        '            exp_annotations: {summary: "API scrape failed; check process and database"}\n'
        "      - eval_time: 3m\n"
        "        alertname: QueueStalled\n"
        "        exp_alerts:\n"
        "          - exp_labels: {severity: warning}\n"
        '            exp_annotations: {summary: "Oldest queued job exceeds 120s; inspect worker"}\n'
        "      - eval_time: 5m\n"
        "        alertname: APIUnavailable\n"
        "        exp_alerts: []\n",
        encoding="utf-8",
    )
    (sl_dir / "backup_restore_drill.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "WORKDIR=\"$(mktemp -d /tmp/crucible-backup-XXXXXX)\"\n"
        "trap 'rm -rf \"$WORKDIR\"' EXIT\n"
        "echo '[1/4] Generating ephemeral age encryption keypair...'\n"
        "age-keygen -o \"$WORKDIR/backup.key\" 2>\"$WORKDIR/key.pub.txt\"\n"
        "PUB=\"$(grep -o 'age1[a-z0-9]*' \"$WORKDIR/backup.key\" | head -n1)\"\n"
        "echo '[2/4] Dumping live PostgreSQL orders table & encrypting with age...'\n"
        "pg_dump -h 127.0.0.1 -p 5432 -U operator -d orders --data-only --table=orders | head -n 50 | age -r \"$PUB\" -o \"$WORKDIR/orders.sql.age\"\n"
        "ls -lh \"$WORKDIR/orders.sql.age\"\n"
        "echo '[3/4] Verifying ciphertext decryption & integrity...'\n"
        "LINES=\"$(age -d -i \"$WORKDIR/backup.key\" \"$WORKDIR/orders.sql.age\" | wc -l)\"\n"
        "echo \"[4/4] Encrypted backup & restore verification PASSED ($LINES SQL lines decrypted).\"\n",
        encoding="utf-8",
    )


def _seed_lab11(root: Path, broken: bool) -> None:
    """Principal P0 Capstone: Simultaneous LIVE Postgres 16 + PgBouncer + NGINX TLS 1.3 meltdown."""
    _seed_lab1(root, broken=broken)
    _seed_lab2(root, broken=broken)


def provision_workspace(
    root: Path, template_id: str, sandbox_id: str, arm_fault: bool = False
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(parents=True, exist_ok=True)

    seeders = {
        "lab0-free-range": _seed_lab0_free_range,
        "lab1-core-engine": _seed_lab1,
        "lab2-linux-tls": _seed_lab2,
        "lab3-lakehouse-wap": _seed_lab3,
        "lab4-rag-acl": _seed_lab4,
        "lab5-raft-internals": _seed_lab5,
        "lab6-k8s-ebpf": _seed_lab6,
        "lab7-linux-sre": seed_lab7,
        "lab8-scale-api": seed_lab8,
        "lab9-iac-iam": seed_lab9,
        "lab10-ai-gpu-mcp": seed_lab10,
        "lab11-p0-capstone": _seed_lab11,
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
        f"- Edit files in the Workbench `Live Files` tab or directly in bash — both stay synced\n"
        f"- Click `Verify SLA & Sign` to run the immutable root-owned grader and mint your SHA-256 receipt\n",
        encoding="utf-8",
    )

    _write_executable(
        root / "bin" / "hint",
        f"#!/usr/bin/env bash\necho 'REMEDIATION HINT: {fault.remediation_hint}'\n",
    )
    _write_executable(
        root / "bin" / "check-sla",
        "#!/usr/bin/env bash\n"
        "echo '[crucible-grader] Click \"Verify SLA & Sign\" in the Workbench header to run the immutable root-owned grader.'\n",
    )
    _chown_tree(root)


def arm_scenario_fault(
    root: Path,
    template_id: str,
    sandbox_id: str,
    scenario_id: str | None = None,
    seed: int | None = None,
) -> RealLabFault:
    spec = get_scenario_spec(template_id, scenario_id=scenario_id, seed=seed)
    provision_workspace(root, template_id, sandbox_id, arm_fault=True)
    # Apply scenario-specific secondary fault configs so EVERY scenario has a distinct, graded fault
    if spec.scenario_id == "pgbouncer_session_mode_starvation":
        pgb = root / "config" / "pgbouncer.ini"
        if pgb.exists():
            txt = pgb.read_text(encoding="utf-8")
            txt = txt.replace("pool_mode = transaction", "pool_mode = session")
            txt = txt.replace("max_client_conn = 500", "max_client_conn = 12")
            pgb.write_text(txt, encoding="utf-8")
        (root / "config" / "pgbouncer-strict.flag").write_text("require_transaction_mode=1\n", encoding="utf-8")
    elif spec.scenario_id == "redis_maxmemory_noeviction_oom":
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config" / "redis.conf").write_text(
            "maxmemory 32mb\nmaxmemory-policy noeviction\n",
            encoding="utf-8",
        )
        if _port_open(6379) and shutil.which("redis-cli"):
            subprocess.run(["redis-cli", "CONFIG", "SET", "maxmemory-policy", "noeviction"], check=False, capture_output=True, timeout=3)
    elif spec.scenario_id == "pg_blocking_lock_storm":
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config" / "postgres-guard.conf").write_text(
            "# BROKEN: Missing idle_in_transaction_session_timeout & lock_timeout\n"
            "idle_in_transaction_session_timeout = 0\n"
            "lock_timeout = 0\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "pg_wal_bloat_and_vacuum_freeze":
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "config" / "postgres-guard.conf").write_text(
            "# BROKEN: MVCC dead-tuple bloat & WAL checkpoint storm\n"
            "autovacuum_vacuum_scale_factor = 0.50\n"
            "max_wal_size = 128\n"
            "idle_in_transaction_session_timeout = 0\n",
            encoding="utf-8",
        )
        (root / "logs" / "pg_vacuum.log").write_text(
            "WARNING: table orders dead_tuple_ratio=0.68 (bloat_mb=4820) — autovacuum skipped (scale_factor=0.50)\n"
            "WARNING: checkpoints occurring every 14 seconds (max_wal_size=128MB too small, WAL rate 14GB/hr)\n"
            "WARNING: xmin horizon pinned by idle-in-transaction pid=4128 (age=1.82B txids)\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "nginx_weak_tls_and_missing_hsts":
        (root / "nginx").mkdir(parents=True, exist_ok=True)
        (root / "nginx" / "security.conf").write_text(
            "# BROKEN: Weak TLSv1/1.1 protocols enabled and Strict-Transport-Security header missing\n"
            "ssl_protocols TLSv1 TLSv1.1 TLSv1.2;\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "nginx_413_body_and_worker_limit":
        (root / "nginx").mkdir(parents=True, exist_ok=True)
        (root / "nginx" / "upload.conf").write_text(
            "# BROKEN: Upload cap 1k causes HTTP 413 and worker_connections 16 starves traffic\n"
            "client_max_body_size 1k;\n"
            "worker_connections 16;\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "tc_netem_packet_loss_tail_collapse":
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "config" / "netem.conf").write_text(
            "# BROKEN: Cross-AZ tc netem loss + CUBIC throughput collapse\n"
            "loss_pct = 2.5\n"
            "delay_ms = 45\n"
            "congestion_control = cubic\n",
            encoding="utf-8",
        )
        (root / "logs" / "netem.log").write_text(
            "NETEM_ALERT: eth0 qdisc netem loss 2.5% delay 45ms · TCP CUBIC cwnd collapsed to 4 segments · p99=3420ms\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "wap_duplicate_event_idempotency":
        (root / "wap").mkdir(parents=True, exist_ok=True)
        (root / "wap" / "dedup_required.flag").write_text("require_event_id_dedup=1\n", encoding="utf-8")
    elif spec.scenario_id == "mcp_unbounded_agent_spend_loop":
        (root / "mcp").mkdir(parents=True, exist_ok=True)
        (root / "mcp" / "policy.json").write_text(
            json.dumps(
                {
                    "max_usd": 500.0,
                    "max_steps": 999,
                    "require_approval_for_writes": False,
                    "allowed_tools": ["*"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "raft_gc_pause_stale_lease":
        (root / "raft").mkdir(parents=True, exist_ok=True)
        (root / "raft" / "lease_config.json").write_text(
            json.dumps(
                {
                    "lease_ttl_ms": 60000,
                    "require_storage_fencing": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "raft_isr_lag_and_fencing_storm":
        (root / "raft").mkdir(parents=True, exist_ok=True)
        (root / "raft" / "cluster.json").write_text(
            json.dumps(
                {
                    "replication_factor": 3,
                    "min_insync_replicas": 1,
                    "acks": "1",
                    "unclean_leader_election": True,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "cilium_dns53_egress_blackhole":
        (root / "k8s").mkdir(parents=True, exist_ok=True)
        (root / "k8s" / "require_dns53.flag").write_text("require_dns53=1\n", encoding="utf-8")
    elif spec.scenario_id == "linux_emfile_accept_storm":
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config" / "sysctl.conf").write_text(
            "# BROKEN: Kernel socket backlog & file-max starved under accept storm\n"
            "fs.file-max = 1024\n"
            "net.core.somaxconn = 16\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "cgroup_oom_kill_and_cpu_throttle":
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "config" / "cgroup.conf").write_text(
            "# BROKEN: cgroup v2 memory.max triggers OOM-kill (Exit 137) & cpu.max CFS throttling\n"
            "memory_max_mb = 128\n"
            "cpu_quota_us = 5000\n"
            "cpu_period_us = 100000\n",
            encoding="utf-8",
        )
        (root / "logs" / "dmesg_oom.log").write_text(
            "[41822.904112] memory: usage 131072kB, limit 131072kB, failcnt 8412\n"
            "[41822.904189] Memory cgroup out of memory: Killed process 2190 (worker) total-vm:512400kB, anon-rss:128900kB (Exit 137)\n"
            "[41824.110002] cpu.stat nr_throttled=41209 throttled_usec=18429000 (cpu.max=5000 100000)\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "hot_tenant_boundary_burst_and_retry":
        (root / "api").mkdir(parents=True, exist_ok=True)
        (root / "api" / "strict_boundary.flag").write_text("require_sliding_boundary_check=1\n", encoding="utf-8")
    elif spec.scenario_id == "tf_concurrent_state_corruption_and_passrole":
        (root / "iam").mkdir(parents=True, exist_ok=True)
        (root / "iam" / "trust.json").write_text(
            json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "sts:AssumeRole"}],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif spec.scenario_id == "vllm_prefix_cache_bust_and_rfc1918_pivot":
        (root / "vllm").mkdir(parents=True, exist_ok=True)
        (root / "vllm" / "strict_rfc1918.flag").write_text("require_rfc1918_and_seqs=1\n", encoding="utf-8")
    elif spec.scenario_id == "principal_black_friday_cascade_p0":
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config" / "redis.conf").write_text(
            "maxmemory 32mb\nmaxmemory-policy noeviction\n",
            encoding="utf-8",
        )
    (root / "README.md").write_text(
        f"# CRUCIBLE LIVE LINUX WAR-ROOM · {template_id}\n"
        f"Sandbox ID: {sandbox_id}\n"
        f"Active Scenario: {spec.title} ({spec.difficulty})\n\n"
        f"## Incident Alert\n{spec.symptom}\n",
        encoding="utf-8",
    )
    _chown_tree(root)
    return RealLabFault(
        fault_id=spec.scenario_id,
        symptom=spec.symptom,
        remediation_hint=spec.remediation_hint,
    )


def scaffold_workspace_project(root: Path, project_id: str, *, use_reference: bool = False) -> dict[str, Any]:
    return scaffold_project_workspace(root, project_id, use_reference=use_reference)


def test_workspace_project(root: Path, project_id: str) -> dict[str, Any]:
    return run_project_stage_tests(root, project_id, _scrubbed_subprocess_env, _unprivileged_preexec)


# ---------------------------------------------------------------------------
# Granular Multi-Check Tamper-Proof SLA Verifier
# ---------------------------------------------------------------------------

def _chk(cid: str, label: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": cid, "label": label, "passed": passed, "status": "pass" if passed else "fail", "detail": detail}


def _verify_lab1_extra_guards(root: Path) -> list[dict[str, Any]]:
    """Verify scenario-specific Lab 1 secondary guards (PgBouncer mode, Redis eviction, Postgres lock & MVCC/WAL)."""
    extra: list[dict[str, Any]] = []

    if (root / "config" / "pgbouncer-strict.flag").exists():
        cfg_path = root / "config" / "pgbouncer.ini"
        mode_val = ""
        max_conn = 0
        if cfg_path.exists():
            for line in cfg_path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("pool_mode") and "=" in s:
                    mode_val = s.split("=", 1)[1].strip().lower()
                elif s.startswith("max_client_conn") and "=" in s:
                    try:
                        max_conn = int(s.split("=", 1)[1].strip())
                    except ValueError:
                        max_conn = 0
        if has_real_postgres() and psycopg is not None:
            try:
                with psycopg.connect("host=127.0.0.1 port=6432 user=operator dbname=pgbouncer", autocommit=True, connect_timeout=3) as conn:
                    for row in conn.execute("SHOW CONFIG").fetchall():
                        k, v = str(row[0]).strip(), str(row[1]).strip()
                        if k == "pool_mode":
                            mode_val = v.lower()
                        elif k == "max_client_conn":
                            max_conn = int(v)
            except Exception:
                pass
        mode_ok = mode_val == "transaction" and max_conn >= 200
        extra.append(
            _chk(
                "pgbouncer_mode",
                "PgBouncer Transaction Mode & max_client_conn >= 200",
                mode_ok,
                f"pool_mode={mode_val}, max_client_conn={max_conn}"
                if mode_ok
                else f"PgBouncer starved: pool_mode={mode_val or 'unset'} (need transaction), max_client_conn={max_conn} (need >= 200)",
            )
        )

    redis_path = root / "config" / "redis.conf"
    if redis_path.exists():
        maxmem_mb = 0
        policy = ""
        for line in redis_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) >= 2 and parts[0].lower() == "maxmemory":
                raw = parts[1].lower()
                try:
                    if raw.endswith("gb"):
                        maxmem_mb = int(float(raw[:-2]) * 1024)
                    elif raw.endswith("mb"):
                        maxmem_mb = int(float(raw[:-2]))
                    elif raw.endswith("m"):
                        maxmem_mb = int(float(raw[:-1]))
                    else:
                        maxmem_mb = int(float(raw) / (1024 * 1024))
                except ValueError:
                    maxmem_mb = 0
            elif len(parts) >= 2 and parts[0].lower() == "maxmemory-policy":
                policy = parts[1].lower()
        redis_ok = maxmem_mb >= 128 and policy in {"allkeys-lru", "volatile-lru", "allkeys-lfu", "volatile-lfu"}
        extra.append(
            _chk(
                "redis_eviction",
                "Redis Eviction Policy (LRU/LFU) & maxmemory >= 128mb",
                redis_ok,
                f"maxmemory={maxmem_mb}mb, maxmemory-policy={policy}"
                if redis_ok
                else f"Redis OOM risk: maxmemory={maxmem_mb}mb (>=128mb), maxmemory-policy={policy or 'unset'} (use allkeys-lru)",
            )
        )

    guard_path = root / "config" / "postgres-guard.conf"
    if guard_path.exists():
        raw_guard = guard_path.read_text(encoding="utf-8")
        kv: dict[str, str] = {}
        for line in raw_guard.splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                kv[k.strip()] = v.strip().rstrip("MBmbmsMS")
        if "lock_timeout" in kv:
            try:
                lt = int(float(kv.get("lock_timeout", "0")))
            except ValueError:
                lt = 0
            try:
                idle_ms = int(float(kv.get("idle_in_transaction_session_timeout", "0")))
            except ValueError:
                idle_ms = 0
            lock_ok = 0 < lt <= 5000 and 0 < idle_ms <= 30000
            extra.append(
                _chk(
                    "pg_lock_guard",
                    "Postgres lock_timeout & idle_in_transaction Guard",
                    lock_ok,
                    f"lock_timeout={lt}ms, idle_in_transaction_session_timeout={idle_ms}ms"
                    if lock_ok
                    else f"Unsafe lock timeouts: lock_timeout={lt} (1..5000ms), idle_in_transaction_session_timeout={idle_ms} (1..30000ms)",
                )
            )
        if "autovacuum_vacuum_scale_factor" in kv or "max_wal_size" in kv:
            try:
                sf = float(kv.get("autovacuum_vacuum_scale_factor", "1.0"))
            except ValueError:
                sf = 1.0
            try:
                wal = int(float(kv.get("max_wal_size", "0")))
            except ValueError:
                wal = 0
            try:
                idle_ms = int(float(kv.get("idle_in_transaction_session_timeout", "0")))
            except ValueError:
                idle_ms = 0
            vac_ok = sf <= 0.05 and wal >= 2048 and 0 < idle_ms <= 30000
            extra.append(
                _chk(
                    "pg_mvcc_wal",
                    "Postgres MVCC Autovacuum & WAL Guard",
                    vac_ok,
                    f"scale_factor={sf}, max_wal_size={wal}MB, idle_tx_timeout={idle_ms}ms"
                    if vac_ok
                    else f"Unsafe MVCC/WAL config: scale_factor={sf} (<=0.05), max_wal_size={wal} (>=2048), idle_tx={idle_ms} (1..30000)",
                )
            )
    return extra


def _verify_lab1_checks(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    if has_real_postgres() and psycopg is not None:
        # Check 1: Live Postgres 16 Index Scan
        idx_ok = False
        idx_detail = ""
        try:
            with psycopg.connect("host=127.0.0.1 port=5432 user=operator dbname=orders", connect_timeout=3) as conn:
                plan_json = conn.execute(
                    "EXPLAIN (FORMAT JSON) SELECT id, amount_cents FROM orders "
                    "WHERE tenant_id = 'tenant_07' ORDER BY created_at DESC LIMIT 25"
                ).fetchone()[0]  # type: ignore[index]
            plan_str = json.dumps(plan_json)
            if "Seq Scan" not in plan_str and ("Index Scan" in plan_str or "Index Only Scan" in plan_str):
                idx_ok = True
                idx_detail = "Index Scan active on orders(tenant_id, created_at)"
            else:
                idx_detail = "Live PostgreSQL 16 plan still doing Seq Scan on orders; create composite index on (tenant_id, created_at)"
        except Exception as exc:
            idx_detail = f"PostgreSQL :5432 unreachable: {exc}"
        checks.append(_chk("pg_index", "Postgres 16 Index Scan", idx_ok, idx_detail))

        # Check 2: Live PgBouncer pool >= 25
        pool_ok = False
        pool_val = 0
        pool_detail = ""
        try:
            with psycopg.connect("host=127.0.0.1 port=6432 user=operator dbname=pgbouncer", autocommit=True, connect_timeout=3) as conn:
                for row in conn.execute("SHOW CONFIG").fetchall():
                    if str(row[0]).strip() == "default_pool_size":
                        pool_val = int(str(row[1]).strip())
                        break
            if pool_val >= 25:
                pool_ok = True
                pool_detail = f"Live PgBouncer (:6432) default_pool_size={pool_val}"
            else:
                pool_detail = f"Live PgBouncer (:6432) default_pool_size={pool_val} < 25 (update config/pgbouncer.ini AND reload-pgbouncer)"
        except Exception as exc:
            pool_detail = f"PgBouncer :6432 unreachable: {exc}"
        checks.append(_chk("pgbouncer_pool", "PgBouncer Pool >= 25", pool_ok, pool_detail))

        # Check 3: Live FastAPI /api/orders probe
        api_ok = False
        api_ms = 0.0
        api_detail = ""
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen("http://127.0.0.1:8000/api/orders?tenant_id=tenant_07", timeout=4) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            api_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            if resp.status == 200 and int(body.get("count", 0)) >= 1:
                api_ok = True
                api_detail = f"HTTP 200 OK · {api_ms}ms ({body.get('count')} rows)"
            else:
                api_detail = f"Unexpected response HTTP {resp.status}"
        except Exception as exc:
            api_detail = f"/api/orders probe failed: {exc}"
        checks.append(_chk("orders_api", "Orders API :8000 Live", api_ok, api_detail))

        checks.extend(_verify_lab1_extra_guards(root))

        all_ok = all(c["passed"] for c in checks)
        summary = (
            f"SLA healthy (LIVE Postgres 16 + PgBouncer): Index Scan active · live default_pool_size={pool_val} · /api/orders {api_ms}ms"
            if all_ok
            else next(c["detail"] for c in checks if not c["passed"])
        )
        return all_ok, summary, checks

    # Workspace-lite fallback
    db_path = root / "data" / "orders.db"
    cfg_path = root / "config" / "pgbouncer.ini"
    idx_ok = False
    plan = ""
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            plan = " ".join(
                str(r)
                for r in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT id, amount_cents FROM orders "
                    "WHERE tenant_id='tenant_07' ORDER BY created_at DESC LIMIT 25"
                ).fetchall()
            )
            idx_ok = "SEARCH" in plan.upper()
        finally:
            conn.close()
    checks.append(
        _chk(
            "pg_index",
            "Composite Index Scan",
            idx_ok,
            f"Indexed query plan ({plan})" if idx_ok else f"orders query still doing full SCAN ({plan}); add composite index on (tenant_id, created_at)",
        )
    )
    pool_val = 0
    if cfg_path.exists():
        for line in cfg_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("default_pool_size"):
                try:
                    pool_val = int(line.split("=", 1)[1].strip())
                except ValueError:
                    pool_val = 0
    pool_ok = pool_val >= 25
    checks.append(
        _chk(
            "pgbouncer_pool",
            "PgBouncer Pool >= 25",
            pool_ok,
            f"default_pool_size={pool_val}" if pool_ok else f"PgBouncer default_pool_size={pool_val} too low (need >= 25)",
        )
    )
    checks.extend(_verify_lab1_extra_guards(root))
    all_ok = all(c["passed"] for c in checks)
    summary = (
        f"SLA healthy: indexed query plan ({plan}) + default_pool_size={pool_val}"
        if all_ok
        else next(c["detail"] for c in checks if not c["passed"])
    )
    return all_ok, summary, checks


def _verify_lab2_checks(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    ng_path = root / "nginx" / "upstream.conf"
    dep_path = root / "deploy" / "rollout.yaml"

    ka = 999
    if ng_path.exists():
        for line in ng_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("keepalive_timeout"):
                parts = s.split()
                if len(parts) >= 2:
                    raw = parts[1].rstrip("s;")
                    if raw.isdigit():
                        ka = int(raw)
    ka_ok = ka <= 55
    checks.append(
        _chk(
            "nginx_keepalive",
            "Upstream keepalive_timeout <= 55s",
            ka_ok,
            f"keepalive_timeout={ka}s (< 60s app idle)" if ka_ok else f"nginx keepalive_timeout={ka}s exceeds safe threshold (<= 55s)",
        )
    )

    prestop_ok = False
    prestop_detail = "deploy/rollout.yaml missing"
    if dep_path.exists():
        dep_raw = dep_path.read_text(encoding="utf-8")
        if yaml is not None:
            try:
                doc = yaml.safe_load(dep_raw)
                containers = doc["spec"]["template"]["spec"]["containers"]
                prestop_ok = any(
                    isinstance(c, dict)
                    and isinstance(c.get("lifecycle"), dict)
                    and isinstance(c["lifecycle"].get("preStop"), dict)
                    and bool(c["lifecycle"]["preStop"].get("exec") or c["lifecycle"]["preStop"].get("httpGet"))
                    for c in containers
                )
                prestop_detail = "preStop drain hook active" if prestop_ok else "deploy/rollout.yaml missing lifecycle.preStop hook"
            except Exception as exc:
                prestop_detail = f"Invalid YAML in deploy/rollout.yaml: {exc}"
        else:
            prestop_ok = "preStop" in dep_raw
            prestop_detail = "preStop hook present" if prestop_ok else "deploy/rollout.yaml missing preStop hook"
    checks.append(_chk("k8s_prestop", "K8s preStop Drain Hook", prestop_ok, prestop_detail))

    sec_path = root / "nginx" / "security.conf"
    if sec_path.exists():
        sec_lines = [l.strip() for l in sec_path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
        sec_body = "\n".join(sec_lines)
        has_weak_tls = bool(re.search(r"\bTLSv1(?:\.0|\.1)?(?:\s|;|$)", sec_body))
        has_modern_tls = bool(re.search(r"\bTLSv1\.[23]\b", sec_body))
        has_hsts = "strict-transport-security" in sec_body.lower()
        sec_ok = (not has_weak_tls) and has_modern_tls and has_hsts
        checks.append(
            _chk(
                "nginx_tls_hsts",
                "NGINX Modern TLS 1.2/1.3 & HSTS Header",
                sec_ok,
                "TLSv1.2/1.3 only + Strict-Transport-Security enabled"
                if sec_ok
                else "nginx/security.conf must disable TLSv1/TLSv1.1 and add Strict-Transport-Security header",
            )
        )

    up_path = root / "nginx" / "upload.conf"
    if up_path.exists():
        up_lines = [l.strip() for l in up_path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
        up_body = "\n".join(up_lines)
        body_mb = 0
        m_body = re.search(r"client_max_body_size\s+(\d+)([kmgKMG]?)", up_body)
        if m_body:
            val = int(m_body.group(1))
            unit = m_body.group(2).lower()
            body_mb = val * 1024 if unit == "g" else (val if unit == "m" else (val / 1024.0 if unit == "k" else val / (1024 * 1024)))
        m_wk = re.search(r"worker_connections\s+(\d+)", up_body)
        wk_conn = int(m_wk.group(1)) if m_wk else 0
        up_ok = body_mb >= 10 and wk_conn >= 1024
        checks.append(
            _chk(
                "nginx_upload_workers",
                "NGINX Upload Limit (>=10m) & worker_connections (>=1024)",
                up_ok,
                f"client_max_body_size={body_mb:g}m, worker_connections={wk_conn}"
                if up_ok
                else f"Upload/worker limit too low: body={body_mb:g}m (>=10m), worker_connections={wk_conn} (>=1024)",
            )
        )

    netem_path = root / "config" / "netem.conf"
    if netem_path.exists():
        nkv: dict[str, str] = {}
        for line in netem_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                nkv[k.strip()] = v.strip().lower()
        try:
            loss_val = float(nkv.get("loss_pct", "99"))
        except ValueError:
            loss_val = 99.0
        cc = nkv.get("congestion_control", "")
        netem_ok = loss_val <= 0.1 and cc == "bbr"
        checks.append(
            _chk(
                "tcp_netem_bbr",
                "TCP BBR & Loss Cleared (<= 0.1%)",
                netem_ok,
                f"congestion_control={cc}, loss_pct={loss_val}%"
                if netem_ok
                else f"Network degraded: congestion_control={cc or 'unset'} (need bbr), loss_pct={loss_val}% (need <= 0.1%)",
            )
        )

    if has_real_nginx():
        # Security: block dynamic shared-object loading (`load_module`) and run `nginx -t` unprivileged.
        nginx_dir = root / "nginx"
        has_forbidden_load_module = False
        if nginx_dir.exists():
            for cfg in nginx_dir.rglob("*.conf"):
                try:
                    if re.search(r"^\s*load_module\b", cfg.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE):
                        has_forbidden_load_module = True
                        break
                except OSError:
                    pass
        if has_forbidden_load_module:
            syn_ok = False
            syn_detail = "Forbidden directive `load_module` detected in nginx config"
        else:
            chk = subprocess.run(
                ["nginx", "-t", "-c", str(root / "nginx" / "nginx.conf")],
                env=_scrubbed_subprocess_env(root),
                preexec_fn=_unprivileged_preexec(),
                capture_output=True,
                text=True,
                timeout=5,
            )
            syn_ok = chk.returncode == 0
            syn_detail = "nginx -t syntax valid" if syn_ok else (chk.stderr or chk.stdout).strip()[:160]
        checks.append(
            _chk(
                "nginx_syntax",
                "NGINX Config Syntax (nginx -t)",
                syn_ok,
                syn_detail,
            )
        )
        curl_chk = subprocess.run(
            ["curl", "-skf", "https://127.0.0.1:8443/health"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        tls_ok = curl_chk.returncode == 0 and "edge-api" in curl_chk.stdout
        checks.append(
            _chk(
                "tls_endpoint",
                "Live TLS 1.3 :8443 -> Uvicorn",
                tls_ok,
                "https://127.0.0.1:8443/health 200 OK" if tls_ok else "TLS :8443 proxy health check failed (run reload-nginx)",
            )
        )

    all_ok = all(c["passed"] for c in checks)
    summary = (
        f"SLA healthy (LIVE NGINX TLS 1.3): nginx -t OK · keepalive_timeout={ka}s · https://:8443 200 OK · preStop verified"
        if (all_ok and has_real_nginx())
        else (f"SLA healthy: keepalive_timeout={ka}s and preStop drain hook active" if all_ok else next(c["detail"] for c in checks if not c["passed"]))
    )
    return all_ok, summary, checks


def _verify_lab3_checks(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    gate = root / "wap" / "publish_gate.py"
    if not gate.exists():
        c = [_chk("wap_exec", "WAP Publish Gate", False, "wap/publish_gate.py missing")]
        return False, "wap/publish_gate.py missing", c

    dedup_required = (root / "wap" / "dedup_required.flag").exists()
    hidden_batch = [
        {"event_id": "h_1", "tenant_id": "alpha", "revenue_cents": 1200},
        {"event_id": "h_2", "tenant_id": None, "revenue_cents": 5000},
        {"event_id": "h_3", "tenant_id": "   ", "revenue_cents": 3200},
        {"event_id": "h_4", "tenant_id": "beta", "revenue_cents": 8900},
        {"event_id": "h_5", "revenue_cents": 4100},
        {"event_id": "h_6", "tenant_id": "gamma", "revenue_cents": 2500},
    ]
    if dedup_required:
        hidden_batch.append({"event_id": "h_1", "tenant_id": "alpha", "revenue_cents": 1200})
        hidden_batch.append({"event_id": "h_4", "tenant_id": "beta", "revenue_cents": 8900})
    checks: list[dict[str, Any]] = []
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
        exec_ok = proc.returncode == 0
        checks.append(_chk("wap_exec", "WAP Gate Execution", exec_ok, "Ran cleanly" if exec_ok else (proc.stderr or proc.stdout).strip()[:160]))
        curated_path = td_path / "wap" / "curated.jsonl"
        dlq_path = td_path / "wap" / "dlq.jsonl"
        clean_ok = False
        count_ok = False
        clean_detail = "curated.jsonl / dlq.jsonl missing"
        count_detail = "Not evaluated"
        if exec_ok and curated_path.exists() and dlq_path.exists():
            curated = [json.loads(l) for l in curated_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            dlq = [json.loads(l) for l in dlq_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            clean_ok = not any(not (isinstance(r.get("tenant_id"), str) and r["tenant_id"].strip()) for r in curated)
            clean_detail = "0 poisoned rows in curated.jsonl" if clean_ok else "curated.jsonl still contains NULL/blank tenant_id rows!"
            curated_ids = [r.get("event_id") for r in curated]
            unique_ok = len(curated_ids) == len(set(curated_ids))
            expected_dlq = 5 if dedup_required else 3
            count_ok = len(curated) == 3 and (len(dlq) == expected_dlq if not dedup_required else unique_ok)
            count_detail = (
                f"3 unique clean curated, duplicates & poisoned quarantined"
                if (count_ok and unique_ok)
                else f"Expected 3 unique curated rows (dedup_required={dedup_required}), got curated={len(curated)} unique={len(set(curated_ids))} dlq={len(dlq)}"
            )
        checks.append(_chk("wap_quarantine", "Zero Poisoned Rows Published", clean_ok, clean_detail))
        checks.append(_chk("wap_counts", "Hidden Adversarial Audit Split", count_ok, count_detail))
        if dedup_required:
            dedup_pass = bool(exec_ok and curated_path.exists() and len([json.loads(l).get("event_id") for l in curated_path.read_text(encoding="utf-8").splitlines() if l.strip()]) == len(set(json.loads(l).get("event_id") for l in curated_path.read_text(encoding="utf-8").splitlines() if l.strip())) == 3)
            checks.append(_chk("wap_dedup", "Idempotent event_id Deduplication", dedup_pass, "0 duplicate event_ids in curated.jsonl" if dedup_pass else "Duplicate event_ids leaked into curated.jsonl!"))

    # Real DuckDB Point-in-Time ASOF Join audit (executes real DuckDB in Firecracker v5; strict SQL check fallback on hosts without duckdb)
    duckdb_script = root / "wap" / "duckdb_pit_audit.py"
    if duckdb_script.exists():
        has_duckdb = False
        try:
            import duckdb as _duckdb_check  # noqa: F401
            has_duckdb = True
        except Exception:
            has_duckdb = False

        if has_duckdb:
            dproc = subprocess.run(
                [sys.executable, "wap/duckdb_pit_audit.py"],
                cwd=str(root),
                env=_scrubbed_subprocess_env(root),
                preexec_fn=_unprivileged_preexec(),
                capture_output=True,
                text=True,
                timeout=8,
            )
            pit_ok = dproc.returncode == 0 and "DUCKDB_PIT_PASS" in dproc.stdout
            pit_detail = (
                "Live DuckDB ASOF JOIN verified (0 future feature leaks)"
                if pit_ok
                else (dproc.stderr or dproc.stdout).strip()[:180]
            )
        else:
            code_lines = [
                ln for ln in duckdb_script.read_text(encoding="utf-8").splitlines()
                if not ln.lstrip().startswith(("#", "--"))
            ]
            active_sql = "\n".join(code_lines).upper()
            pit_ok = "ASOF JOIN" in active_sql and ("PRED_TS >= E.EVENT_TS" in active_sql or "EVENT_TS <= S.PRED_TS" in active_sql)
            pit_detail = (
                "DuckDB ASOF JOIN point-in-time predicate verified"
                if pit_ok
                else "wap/duckdb_pit_audit.py must use ASOF JOIN with pred_ts >= event_ts (zero future leakage)"
            )
        checks.append(_chk("duckdb_pit_asof", "DuckDB Point-in-Time ASOF Join (Zero Leakage)", pit_ok, pit_detail))

    all_ok = all(c["passed"] for c in checks)
    return all_ok, ("SLA healthy: WAP gate + DuckDB ASOF point-in-time audit passed (0 poisoned/leaked rows)" if all_ok else next(c["detail"] for c in checks if not c["passed"])), checks


def _verify_lab4_checks(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    retriever = root / "rag" / "retriever.py"
    policy_path = root / "mcp" / "policy.json"
    checks: list[dict[str, Any]] = []

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
assert retrieve_for_tenant(CORPUS, tenant_id="ghost_tenant", top_k=2) == []
print("HIDDEN_ACL_PASS")
"""
    acl_ok = False
    acl_detail = "rag/retriever.py missing"
    if retriever.exists():
        proc = subprocess.run(
            [sys.executable, "-c", hidden_test],
            cwd=str(root),
            env=_scrubbed_subprocess_env(root),
            preexec_fn=_unprivileged_preexec(),
            capture_output=True,
            text=True,
            timeout=8,
        )
        acl_ok = proc.returncode == 0 and "HIDDEN_ACL_PASS" in proc.stdout
        acl_detail = "Pre-filter ACL passed (0 leaks, 100% small-tenant recall)" if acl_ok else (proc.stderr or proc.stdout).strip()[:180]
    checks.append(_chk("rag_prefilter", "Pre-Filter Tenant ACL (Hidden Red-Team)", acl_ok, acl_detail))

    budget_ok = False
    writes_ok = False
    budget_detail = "mcp/policy.json missing"
    writes_detail = "mcp/policy.json missing"
    if policy_path.exists():
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            max_usd = float(policy.get("max_usd", 999))
            max_steps = int(policy.get("max_steps", 999))
            budget_ok = max_usd <= 2.0 and max_steps <= 12
            budget_detail = f"max_usd=${max_usd}, max_steps={max_steps}" if budget_ok else f"Unsafe caps: max_usd={max_usd} (<=2), max_steps={max_steps} (<=12)"
            writes_ok = policy.get("require_approval_for_writes") is True
            writes_detail = "require_approval_for_writes=true" if writes_ok else "require_approval_for_writes must be true"
            if "allowed_tools" in policy:
                tools = policy.get("allowed_tools")
                tools_ok = isinstance(tools, list) and len(tools) >= 1 and "*" not in tools
                checks.append(
                    _chk(
                        "mcp_allowlist",
                        "MCP Explicit Tool Allowlist (No Wildcard)",
                        tools_ok,
                        f"Scoped allowlist: {tools}" if tools_ok else "mcp/policy.json allowed_tools must be a non-empty list without '*'",
                    )
                )
        except ValueError as exc:
            budget_detail = f"Invalid JSON: {exc}"
    checks.append(_chk("mcp_budget", "Bounded MCP Budget Caps", budget_ok, budget_detail))
    checks.append(_chk("mcp_writes", "MCP Write Approval Gate", writes_ok, writes_detail))

    # Real PostgreSQL + pgvector Pre-Filter SQL check (executes live on Postgres + pgvector inside Firecracker v5!)
    pgvec_sql = root / "rag" / "pgvector_acl_lab.sql"
    if pgvec_sql.exists():
        sql_text = pgvec_sql.read_text(encoding="utf-8")
        if has_real_postgres() and _port_open(5432) and psycopg is not None:
            pgvec_ok = False
            pgvec_detail = "pgvector query failed"
            try:
                # Security: execute student-writable SQL strictly as unprivileged `operator` role, never `postgres` superuser.
                with psycopg.connect("host=127.0.0.1 port=5432 user=operator dbname=orders", autocommit=True) as conn:
                    cur = conn.cursor()
                    stmts = [s.strip() for s in sql_text.split(";") if s.strip() and not all(ln.strip().startswith("--") or not ln.strip() for ln in s.splitlines())]
                    last_rows: list[Any] = []
                    for st in stmts:
                        cur.execute(st)
                        if cur.description is not None:
                            last_rows = cur.fetchall()
                    tenants = [r[1] for r in last_rows] if last_rows else []
                    pgvec_ok = len(last_rows) == 2 and all(t == "small_co" for t in tenants)
                    pgvec_detail = (
                        f"Live Postgres+pgvector pre-filter returned {len(last_rows)} small_co rows (0 mega_corp leaks)"
                        if pgvec_ok
                        else f"pgvector ACL query returned {len(last_rows)} row(s) tenants={tenants}; expected 2 small_co rows!"
                    )
            except Exception as exc:
                pgvec_detail = f"Live pgvector error: {str(exc)[:160]}"
        else:
            active_sql = "\n".join(
                ln for ln in sql_text.splitlines() if not ln.lstrip().startswith("--")
            ).upper()
            # Ensure WHERE tenant_id = 'small_co' is applied BEFORE ORDER BY ... LIMIT (not post-filtered in outer subquery)
            where_idx = active_sql.rfind("WHERE TENANT_ID")
            order_idx = active_sql.rfind("ORDER BY EMBEDDING")
            has_subquery_postfilter = "FROM (" in active_sql and where_idx > order_idx
            pgvec_ok = where_idx != -1 and order_idx != -1 and where_idx < order_idx and not has_subquery_postfilter
            pgvec_detail = (
                "pgvector SQL pre-filters WHERE tenant_id BEFORE vector ORDER BY + LIMIT"
                if pgvec_ok
                else "rag/pgvector_acl_lab.sql post-filters after LIMIT (starves small_co); move WHERE tenant_id before ORDER BY"
            )
        checks.append(_chk("pgvector_acl_sql", "PostgreSQL pgvector Pre-Filter SQL", pgvec_ok, pgvec_detail))

    all_ok = all(c["passed"] for c in checks)
    return all_ok, ("SLA healthy: hidden multi-tenant pre-filter ACL + live pgvector SQL + bounded MCP budget verified" if all_ok else next(c["detail"] for c in checks if not c["passed"])), checks


def _verify_lab5_checks(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    guard = root / "raft" / "storage_guard.py"
    hidden_test = """
import sys
sys.path.insert(0, "raft")
from storage_guard import FencedStorage

s = FencedStorage()
assert s.write("acct", "100", fencing_token=10) is True
assert s.write("acct", "250", fencing_token=15) is True
assert s.write("acct", "STALE_14", fencing_token=14) is False, "Zombie leader term=14 was accepted!"
assert s.write("acct", "STALE_01", fencing_token=1) is False, "Ancient leader term=1 was accepted!"
assert s.data["acct"] == "250", "Committed state corrupted!"
assert s.write("acct", "300", fencing_token=15) is True
assert s.write("acct", "400", fencing_token=16) is True
assert s.write("acct", "STALE_15", fencing_token=15) is False, "Stale term=15 accepted after term=16!"
assert s.data["acct"] == "400"
print("HIDDEN_RAFT_PASS")
"""
    ok = False
    detail = "raft/storage_guard.py missing"
    if guard.exists():
        proc = subprocess.run(
            [sys.executable, "-c", hidden_test],
            cwd=str(root),
            env=_scrubbed_subprocess_env(root),
            preexec_fn=_unprivileged_preexec(),
            capture_output=True,
            text=True,
            timeout=8,
        )
        ok = proc.returncode == 0 and "HIDDEN_RAFT_PASS" in proc.stdout
        detail = "All stale zombie writes rejected; committed term preserved" if ok else (proc.stderr or proc.stdout).strip()[:180]
    checks = [_chk("raft_fencing", "Monotonic Split-Brain Fencing (Hidden Suite)", ok, detail)]

    lease_path = root / "raft" / "lease_config.json"
    if lease_path.exists():
        lease_ok = False
        lease_detail = "Invalid JSON in raft/lease_config.json"
        try:
            lcfg = json.loads(lease_path.read_text(encoding="utf-8"))
            ttl = int(lcfg.get("lease_ttl_ms", 999999))
            req_fence = lcfg.get("require_storage_fencing") is True
            lease_ok = 0 < ttl <= 10000 and req_fence
            lease_detail = (
                f"lease_ttl_ms={ttl}, require_storage_fencing=true"
                if lease_ok
                else f"Unsafe lease config: lease_ttl_ms={ttl} (<=10000), require_storage_fencing={req_fence}"
            )
        except Exception as exc:
            lease_detail = f"Invalid raft/lease_config.json: {exc}"
        checks.append(_chk("raft_lease", "Bounded Leader Lease & Storage Fencing Guard", lease_ok, lease_detail))

    cluster_path = root / "raft" / "cluster.json"
    if cluster_path.exists():
        isr_ok = False
        isr_detail = "Invalid JSON in raft/cluster.json"
        try:
            cfg = json.loads(cluster_path.read_text(encoding="utf-8"))
            acks_ok = str(cfg.get("acks", "")).lower() == "all"
            rf = int(cfg.get("replication_factor", 0))
            min_isr = int(cfg.get("min_insync_replicas", 0))
            unclean = bool(cfg.get("unclean_leader_election", False))
            isr_ok = acks_ok and rf >= 3 and min_isr >= 2 and not unclean
            isr_detail = (
                f"acks=all, RF={rf}, min_insync_replicas={min_isr}, unclean_leader_election=false"
                if isr_ok
                else f"Unsafe ISR durability: acks={cfg.get('acks')}, RF={rf}, min_isr={min_isr}, unclean={unclean}"
            )
        except Exception as exc:
            isr_detail = f"Invalid raft/cluster.json: {exc}"
        checks.append(_chk("raft_isr", "Kafka/Raft Quorum Durability (acks=all, min.isr>=2)", isr_ok, isr_detail))

    all_ok = all(c["passed"] for c in checks)
    return all_ok, ("SLA healthy: hidden multi-term split-brain adversarial suite & quorum durability passed" if all_ok else next(c["detail"] for c in checks if not c["passed"])), checks


def _verify_lab6_checks(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    np_path = root / "k8s" / "networkpolicy.yaml"
    pdb_path = root / "k8s" / "pdb.yaml"
    checks: list[dict[str, Any]] = []

    np_ok = False
    np_detail = "k8s/networkpolicy.yaml missing"
    if np_path.exists():
        np_text = np_path.read_text(encoding="utf-8")
        if yaml is not None:
            try:
                np_doc = yaml.safe_load(np_text)
                policy_types = np_doc.get("spec", {}).get("policyTypes", []) if isinstance(np_doc, dict) else []
                egress = np_doc.get("spec", {}).get("egress", []) if isinstance(np_doc, dict) else []
                ports_found: set[tuple[str, int]] = set()
                for rule in egress or []:
                    if isinstance(rule, dict):
                        for p in rule.get("ports", []) or []:
                            if isinstance(p, dict) and p.get("port") is not None:
                                try:
                                    ports_found.add((str(p.get("protocol", "TCP")).upper(), int(p["port"])))
                                except (ValueError, TypeError):
                                    pass
                np_ok = isinstance(np_doc, dict) and np_doc.get("kind") == "NetworkPolicy" and "Egress" in policy_types and ("TCP", 6432) in ports_found
                np_detail = "Egress TCP:6432 (PgBouncer) allowed" if np_ok else "NetworkPolicy egress still blocks TCP port 6432"
                if (root / "k8s" / "require_dns53.flag").exists():
                    dns53_ok = ("UDP", 53) in ports_found or ("TCP", 53) in ports_found
                    checks.append(
                        _chk(
                            "k8s_dns53",
                            "NetworkPolicy CoreDNS Egress :53 Allowed",
                            dns53_ok,
                            "CoreDNS port 53 egress allowed" if dns53_ok else "NetworkPolicy egress still blocks CoreDNS port 53 (UDP/TCP)",
                        )
                    )
            except Exception as exc:
                np_detail = f"Invalid YAML: {exc}"
        else:
            np_ok = "6432" in np_text
            np_detail = "Port 6432 allowed" if np_ok else "Port 6432 blocked"
    checks.append(_chk("k8s_netpol", "NetworkPolicy Egress TCP :6432", np_ok, np_detail))

    pdb_ok = False
    pdb_detail = "k8s/pdb.yaml missing"
    if pdb_path.exists():
        pdb_text = pdb_path.read_text(encoding="utf-8")
        if yaml is not None:
            try:
                pdb_doc = yaml.safe_load(pdb_text)
                spec = pdb_doc.get("spec", {}) if isinstance(pdb_doc, dict) else {}
                min_avail = spec.get("minAvailable")
                max_unavail = spec.get("maxUnavailable")
                if max_unavail is not None:
                    pdb_ok = int(str(max_unavail).rstrip("%")) >= 1
                elif min_avail is not None:
                    raw = str(min_avail).strip()
                    pdb_ok = int(raw[:-1]) <= 80 if raw.endswith("%") else int(raw) <= 3
                pdb_detail = f"Safe drain budget (minAvailable={min_avail}, maxUnavailable={max_unavail})" if pdb_ok else f"PDB blocks AZ drains (minAvailable={min_avail}; set <= 80% or maxUnavailable: 1)"
            except Exception as exc:
                pdb_detail = f"Invalid YAML: {exc}"
        else:
            pdb_ok = "100%" not in pdb_text
            pdb_detail = "PDB drain safe" if pdb_ok else "minAvailable: 100% blocks drains"
    checks.append(_chk("k8s_pdb", "PDB Safe AZ Node Drain", pdb_ok, pdb_detail))

    all_ok = all(c["passed"] for c in checks)
    return all_ok, ("SLA healthy: structural K8s NetworkPolicy allows TCP:6432 egress & PDB permits safe AZ drains" if all_ok else next(c["detail"] for c in checks if not c["passed"])), checks


def _verify_lab11_checks(root: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    ok1, d1, c1 = _verify_lab1_checks(root)
    ok2, d2, c2 = _verify_lab2_checks(root)
    checks = [*c1, *c2]
    all_ok = ok1 and ok2
    summary = (
        "PRINCIPAL P0 RESOLVED: Live Postgres 16 Index + PgBouncer Pool + NGINX TLS 1.3 + K8s preStop ALL verified!"
        if all_ok
        else (d1 if not ok1 else d2)
    )
    return all_ok, summary, checks


def verify_workspace_checks(root: Path, template_id: str) -> tuple[bool, str, list[dict[str, Any]]]:
    if not root.exists():
        return False, "sandbox workspace missing", [_chk("workspace", "Workspace Mounted", False, "missing")]
    verifiers = {
        "lab0-free-range": _verify_lab11_checks,
        "lab1-core-engine": _verify_lab1_checks,
        "lab2-linux-tls": _verify_lab2_checks,
        "lab3-lakehouse-wap": _verify_lab3_checks,
        "lab4-rag-acl": _verify_lab4_checks,
        "lab5-raft-internals": _verify_lab5_checks,
        "lab6-k8s-ebpf": _verify_lab6_checks,
        "lab7-linux-sre": verify_lab7,
        "lab8-scale-api": lambda r: verify_lab8(r, _scrubbed_subprocess_env, _unprivileged_preexec),
        "lab9-iac-iam": verify_lab9,
        "lab10-ai-gpu-mcp": lambda r: verify_lab10(r, _scrubbed_subprocess_env, _unprivileged_preexec),
        "lab11-p0-capstone": _verify_lab11_checks,
    }
    fn = verifiers.get(template_id)
    if fn is None:
        return False, f"unknown template {template_id}", []
    return fn(root)


def verify_workspace_sla(root: Path, template_id: str) -> tuple[bool, str]:
    ok, detail, _ = verify_workspace_checks(root, template_id)
    return ok, detail


def collect_live_daemons() -> dict[str, bool]:
    return {
        "postgresql": _port_open(5432),
        "pgbouncer": _port_open(6432),
        "redis": _port_open(6379),
        "nginx_tls": _port_open(8443),
        "app_api": _port_open(8000),
    }


def probe_live_telemetry(root: Path, template_id: str) -> dict[str, Any]:
    """Fast live telemetry sample for the Workbench's real-time Datadog-style sparkline."""
    t0 = time.perf_counter()
    healthy, summary, checks = verify_workspace_checks(root, template_id)
    probe_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    # Extract real service latency for Lab 1 / Lab 2 when live daemons are running
    metric_label = "SLA PROBE"
    metric_value_ms = probe_ms
    if template_id == "lab1-core-engine" and has_real_postgres():
        metric_label = "/api/orders p99"
        try:
            q0 = time.perf_counter()
            with urllib.request.urlopen("http://127.0.0.1:8000/api/orders?tenant_id=tenant_07", timeout=2) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            raw_ms = float(body.get("latency_ms", round((time.perf_counter() - q0) * 1000.0, 1)))
            # Reflect PgBouncer pool queueing penalty visibly when pool is starved so sparkline shows real pain vs fix!
            pool_ok = any(c["id"] == "pgbouncer_pool" and c["passed"] for c in checks)
            idx_ok = any(c["id"] == "pg_index" and c["passed"] for c in checks)
            if not idx_ok or not pool_ok:
                metric_value_ms = round(max(raw_ms, 180.0 if not idx_ok else 95.0), 1)
            else:
                metric_value_ms = round(raw_ms, 1)
        except Exception:
            metric_value_ms = 500.0
    elif template_id == "lab2-linux-tls" and has_real_nginx():
        metric_label = "TLS :8443 TTFB"
        q0 = time.perf_counter()
        chk = subprocess.run(
            ["curl", "-skf", "https://127.0.0.1:8443/health"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        raw_ms = round((time.perf_counter() - q0) * 1000.0, 1)
        ka_ok = any(c["id"] == "nginx_keepalive" and c["passed"] for c in checks)
        metric_value_ms = raw_ms if (chk.returncode == 0 and ka_ok) else round(max(raw_ms, 210.0), 1)

    return {
        "healthy": healthy,
        "summary": summary,
        "metric_label": metric_label,
        "latency_ms": metric_value_ms,
        "checks_passing": sum(1 for c in checks if c["passed"]),
        "checks_total": len(checks),
        "checks": checks,
    }
