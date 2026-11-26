"""In-VM Root Control Agent for Hardware-Isolated Crucible Firecracker MicroVMs.

Runs as PID 1 / root inside each ephemeral Fly Firecracker MicroVM (ZERO public IP exposure;
reachable exclusively over Fly's private 6pn WireGuard mesh from the stateless orchestrator).

Exposes internal 6pn-only APIs:
  - GET  /internal/health        (unauthenticated readiness check)
  - GET  /internal/metrics       (live daemons, RAM, Datadog-style telemetry sparkline & live SLA checks)
  - GET  /internal/files         (list editable lab files inside /home/operator)
  - GET  /internal/files/read    (read a sandbox workspace file safely)
  - PUT  /internal/files/write   (write file as `operator` + optional live daemon reload + instant re-grade)
  - POST /internal/chaos         (arm blind production fault)
  - POST /internal/verify        (immutable root-owned multi-check grader)
  - WS   /internal/terminal      (unprivileged `operator` uid=1000 bash PTY with rlimits & heartbeat)
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import pty
import pwd
import resource
import shutil
import signal
import ssl
import struct
import subprocess
import termios
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

try:
    import psycopg  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    psycopg = None

try:
    from grader import (  # type: ignore[import-not-found]
        arm_scenario_fault,
        collect_live_daemons,
        has_real_nginx,
        has_real_postgres,
        list_editable_files,
        probe_live_telemetry,
        provision_workspace,
        read_workspace_file,
        reload_lab_daemon,
        scaffold_workspace_project,
        test_workspace_project,
        verify_workspace_checks,
        write_workspace_file,
    )
except ImportError:
    from orchestrator.grader import (
        arm_scenario_fault,
        collect_live_daemons,
        has_real_nginx,
        has_real_postgres,
        list_editable_files,
        probe_live_telemetry,
        provision_workspace,
        read_workspace_file,
        reload_lab_daemon,
        scaffold_workspace_project,
        test_workspace_project,
        verify_workspace_checks,
        write_workspace_file,
    )

SANDBOX_ID = os.environ.get("SPARTAN_SANDBOX_ID", "sbx_local").strip()
TEMPLATE_ID = os.environ.get("SPARTAN_TEMPLATE", "lab1-core-engine").strip()
MODULE_ID = os.environ.get("SPARTAN_MODULE", "M01").strip()
VM_SECRET = os.environ.get("VM_SESSION_SECRET", "").strip()
EXPIRES_EPOCH = int(os.environ.get("SPARTAN_EXPIRES_AT", str(int(time.time()) + 3600)))
IDLE_TIMEOUT_SECONDS = int(os.environ.get("SPARTAN_IDLE_TIMEOUT_SECONDS", "1200"))
ARM_INITIAL_FAULT = os.environ.get("SPARTAN_ARM_CHAOS", "0").strip().lower() in {"1", "true", "yes"}
INITIAL_SCENARIO_ID = os.environ.get("SPARTAN_SCENARIO_ID", "").strip() or None
WORKSPACE_DIR = Path(os.environ.get("SPARTAN_WORKSPACE_DIR", "/home/operator"))
BOOT_EPOCH = time.time()

_state: dict[str, Any] = {
    "ready": False,
    "active_ws": 0,
    "last_activity": time.time(),
    "expires_epoch": EXPIRES_EPOCH,
    "fault_armed": ARM_INITIAL_FAULT,
    "active_scenario_id": INITIAL_SCENARIO_ID,
}

_loadgen: dict[str, Any] = {
    "active": False,
    "target_rps": 0,
    "actual_rps": 0.0,
    "total_requests": 0,
    "error_count": 0,
    "error_rate_pct": 0.0,
    "p50_ms": 0.0,
    "p95_ms": 0.0,
    "p99_ms": 0.0,
    "started_at": 0.0,
    "stop_at": 0.0,
    "task": None,
}


class WriteFileRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., max_length=262144)
    reload: bool = False


class ChaosBody(BaseModel):
    scenario_id: str | None = Field(default=None, max_length=80)
    seed: int | None = None


class LoadgenBody(BaseModel):
    enabled: bool = True
    rps: int = Field(default=50, ge=1, le=50)
    duration_s: int = Field(default=60, ge=5, le=90)


class ProjectActionBody(BaseModel):
    project_id: str = Field(..., min_length=3, max_length=64)
    use_reference: bool = False


def _verify_token(token: str) -> dict[str, Any] | None:
    if not VM_SECRET or "." not in token:
        return None
    body, sig = token.split(".", 1)
    expected = hmac.new(VM_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    pad = "=" * (-len(body) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict) or claims.get("sid") != SANDBOX_ID:
        return None
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp <= int(time.time()):
        return None
    return claims


def _require_vm_secret(x_vm_session_secret: str | None = Header(default=None)) -> None:
    if not VM_SECRET:
        raise HTTPException(status_code=503, detail="VM_SESSION_SECRET not configured")
    if not x_vm_session_secret or not hmac.compare_digest(x_vm_session_secret, VM_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized VM control request")


def _try_harden_proc() -> None:
    if os.geteuid() == 0:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["mount", "-o", "remount,hidepid=2", "/proc"],
                check=False,
                capture_output=True,
                timeout=2,
            )


def _try_harden_egress_firewall() -> None:
    """Apply fail-safe outbound firewall rules inside Firecracker VM when root + CAP_NET_ADMIN.

    Blocks outbound Fly 6PN lateral scanning (`fdaa::/16` except established/related orchestrator
    return traffic and local DNS `fdaa::3`), RFC1918 probing, and common crypto-mining Stratum ports.
    """
    if os.geteuid() != 0:
        return
    ip6 = shutil.which("ip6tables")
    ip4 = shutil.which("iptables")
    rules: list[list[str]] = []
    if ip6:
        rules.extend(
            [
                [ip6, "-A", "OUTPUT", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
                [ip6, "-A", "OUTPUT", "-o", "lo", "-j", "ACCEPT"],
                [ip6, "-A", "OUTPUT", "-d", "fdaa::/16", "-p", "tcp", "--sport", str(AGENT_PORT), "-j", "ACCEPT"],
                [ip6, "-A", "OUTPUT", "-d", "fdaa::/16", "-j", "DROP"],
            ]
        )
    if ip4:
        for port in ("3333", "4444", "5555", "7777", "8333", "9999", "14444", "45700"):
            rules.append([ip4, "-A", "OUTPUT", "-p", "tcp", "--dport", port, "-j", "DROP"])
        for cidr in ("169.254.169.254/32", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
            rules.append([ip4, "-A", "OUTPUT", "-d", cidr, "-j", "DROP"])
    for cmd in rules:
        with contextlib.suppress(Exception):
            subprocess.run(cmd, check=False, capture_output=True, timeout=2)


def _bootstrap_lab() -> None:
    _try_harden_proc()
    _try_harden_egress_firewall()
    if ARM_INITIAL_FAULT:
        fault = arm_scenario_fault(
            WORKSPACE_DIR,
            TEMPLATE_ID,
            SANDBOX_ID,
            scenario_id=INITIAL_SCENARIO_ID,
        )
        _state["active_scenario_id"] = fault.fault_id
    else:
        provision_workspace(WORKSPACE_DIR, TEMPLATE_ID, SANDBOX_ID, arm_fault=False)
    _state["ready"] = True


def _single_load_probe() -> tuple[bool, float]:
    """Execute one real request against the active local daemon inside this MicroVM."""
    t0 = time.perf_counter()
    try:
        if TEMPLATE_ID in {"lab2-linux-tls"} and has_real_nginx():
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen("https://127.0.0.1:8443/health", timeout=1.5, context=ctx) as resp:
                ok = resp.status == 200
            return ok, round((time.perf_counter() - t0) * 1000.0, 2)
        if TEMPLATE_ID in {"lab1-core-engine", "lab11-p0-capstone"} and has_real_postgres():
            with urllib.request.urlopen("http://127.0.0.1:8000/api/orders?tenant_id=tenant_07", timeout=1.5) as resp:
                ok = resp.status == 200
            return ok, round((time.perf_counter() - t0) * 1000.0, 2)
        # Pure-code labs: fast SLA check burst
        ok, _, _ = verify_workspace_checks(WORKSPACE_DIR, TEMPLATE_ID)
        return ok, round((time.perf_counter() - t0) * 1000.0, 2)
    except Exception:
        return False, round((time.perf_counter() - t0) * 1000.0, 2)


def _loadgen_snapshot() -> dict[str, Any]:
    return {
        "active": bool(_loadgen["active"]),
        "target_rps": int(_loadgen["target_rps"]),
        "actual_rps": float(_loadgen["actual_rps"]),
        "total_requests": int(_loadgen["total_requests"]),
        "error_count": int(_loadgen["error_count"]),
        "error_rate_pct": float(_loadgen["error_rate_pct"]),
        "p50_ms": float(_loadgen["p50_ms"]),
        "p95_ms": float(_loadgen["p95_ms"]),
        "p99_ms": float(_loadgen["p99_ms"]),
        "remaining_s": max(0, int(_loadgen["stop_at"] - time.time())) if _loadgen["active"] else 0,
    }


async def _run_loadgen_loop(target_rps: int, duration_s: int) -> None:
    loop = asyncio.get_running_loop()
    samples: deque[float] = deque(maxlen=250)
    _loadgen["active"] = True
    _loadgen["target_rps"] = target_rps
    _loadgen["total_requests"] = 0
    _loadgen["error_count"] = 0
    _loadgen["started_at"] = time.time()
    _loadgen["stop_at"] = _loadgen["started_at"] + duration_s
    concurrency = max(2, min(10, target_rps // 5))
    try:
        while _loadgen["active"] and time.time() < _loadgen["stop_at"]:
            tick_start = time.perf_counter()
            batch = await asyncio.gather(
                *[loop.run_in_executor(None, _single_load_probe) for _ in range(concurrency)],
                return_exceptions=True,
            )
            for item in batch:
                _loadgen["total_requests"] += 1
                if isinstance(item, tuple):
                    ok, ms = item
                    samples.append(ms)
                    if not ok:
                        _loadgen["error_count"] += 1
                else:
                    _loadgen["error_count"] += 1
            elapsed = max(0.1, time.time() - _loadgen["started_at"])
            _loadgen["actual_rps"] = round(_loadgen["total_requests"] / elapsed, 1)
            _loadgen["error_rate_pct"] = round(
                (_loadgen["error_count"] / max(1, _loadgen["total_requests"])) * 100.0, 1
            )
            if samples:
                ordered = sorted(samples)
                n = len(ordered)
                _loadgen["p50_ms"] = ordered[int(n * 0.50)]
                _loadgen["p95_ms"] = ordered[min(n - 1, int(n * 0.95))]
                _loadgen["p99_ms"] = ordered[min(n - 1, int(n * 0.99))]
            # Pace batches cleanly to respect target_rps without pegging CPU
            target_batch_s = concurrency / max(1.0, float(target_rps))
            sleep_s = max(0.05, target_batch_s - (time.perf_counter() - tick_start))
            await asyncio.sleep(sleep_s)
    finally:
        _loadgen["active"] = False


async def _idle_and_ttl_reaper() -> None:
    while True:
        await asyncio.sleep(20)
        now = time.time()
        expired = now >= int(_state.get("expires_epoch", EXPIRES_EPOCH))
        idle = _state["active_ws"] == 0 and (now - _state["last_activity"]) >= IDLE_TIMEOUT_SECONDS
        if expired or idle:
            os._exit(0)


app = FastAPI(title="Crucible Firecracker VM Agent", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def _on_startup() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _bootstrap_lab)
    asyncio.create_task(_idle_and_ttl_reaper())


@app.get("/internal/health")
def internal_health() -> dict[str, Any]:
    return {
        "status": "ok" if _state["ready"] else "booting",
        "sandbox_id": SANDBOX_ID,
        "template_id": TEMPLATE_ID,
        "backend": "fly-firecracker",
        "ready": _state["ready"],
        "daemons": collect_live_daemons(),
    }


def _collect_live_prometheus_scrape(
    mem_used_mb: int,
    mem_total_mb: int,
    daemons: dict[str, bool],
    telemetry: dict[str, Any],
) -> tuple[dict[str, float | int], str]:
    """Scrape real live Postgres, PgBouncer, NGINX & Linux kernel counters inside this MicroVM."""
    m: dict[str, float | int] = {
        "crucible_vm_memory_used_mb": mem_used_mb,
        "crucible_vm_memory_total_mb": mem_total_mb,
        "crucible_vm_uptime_seconds": round(time.time() - BOOT_EPOCH, 1),
        "crucible_sla_latency_ms": float(telemetry.get("latency_ms", 0.0)),
        "crucible_sla_checks_passing": int(telemetry.get("checks_passing", 0)),
        "crucible_sla_checks_total": int(telemetry.get("checks_total", 0)),
        "crucible_loadgen_rps": float(_loadgen.get("actual_rps", 0.0)),
        "crucible_loadgen_error_rate_pct": float(_loadgen.get("error_rate_pct", 0.0)),
        "crucible_loadgen_p99_ms": float(_loadgen.get("p99_ms", 0.0)),
        "linux_loadavg_1m": 0.0,
        "linux_open_fds": 0,
        "pg_active_connections": 0,
        "pg_waiting_locks": 0,
        "pg_orders_seq_scans": 0,
        "pg_orders_idx_scans": 0,
        "pg_orders_dead_tuples": 0,
        "pg_orders_live_tuples": 0,
        "pgbouncer_cl_active": 0,
        "pgbouncer_cl_waiting": 0,
        "pgbouncer_sv_active": 0,
        "pgbouncer_sv_idle": 0,
        "nginx_up": 1 if daemons.get("nginx") else 0,
        "postgres_up": 1 if daemons.get("postgres") else 0,
        "pgbouncer_up": 1 if daemons.get("pgbouncer") else 0,
        "redis_up": 1 if daemons.get("redis") else 0,
    }

    with contextlib.suppress(OSError, ValueError):
        load_parts = Path("/proc/loadavg").read_text(encoding="utf-8").split()
        if load_parts:
            m["linux_loadavg_1m"] = round(float(load_parts[0]), 2)
    with contextlib.suppress(OSError, ValueError):
        fd_parts = Path("/proc/sys/fs/file-nr").read_text(encoding="utf-8").split()
        if fd_parts and fd_parts[0].isdigit():
            m["linux_open_fds"] = int(fd_parts[0])

    if has_real_postgres() and psycopg is not None:
        with contextlib.suppress(Exception):
            with psycopg.connect(
                "host=127.0.0.1 port=5432 user=operator dbname=orders",
                connect_timeout=1,
            ) as conn:
                act = conn.execute(
                    "SELECT count(*) FILTER (WHERE state = 'active'), "
                    "count(*) FILTER (WHERE wait_event_type = 'Lock') "
                    "FROM pg_stat_activity WHERE datname = 'orders'"
                ).fetchone()
                if act:
                    m["pg_active_connections"] = int(act[0] or 0)
                    m["pg_waiting_locks"] = int(act[1] or 0)
                st = conn.execute(
                    "SELECT coalesce(seq_scan,0), coalesce(idx_scan,0), "
                    "coalesce(n_live_tup,0), coalesce(n_dead_tup,0) "
                    "FROM pg_stat_user_tables WHERE relname = 'orders'"
                ).fetchone()
                if st:
                    m["pg_orders_seq_scans"] = int(st[0] or 0)
                    m["pg_orders_idx_scans"] = int(st[1] or 0)
                    m["pg_orders_live_tuples"] = int(st[2] or 0)
                    m["pg_orders_dead_tuples"] = int(st[3] or 0)

        with contextlib.suppress(Exception):
            with psycopg.connect(
                "host=127.0.0.1 port=6432 user=operator dbname=pgbouncer",
                autocommit=True,
                connect_timeout=1,
            ) as pgb:
                rows = pgb.execute("SHOW POOLS").fetchall()
                for row in rows:
                    if str(row[0]).strip() == "orders":
                        m["pgbouncer_cl_active"] = int(row[2] or 0)
                        m["pgbouncer_cl_waiting"] = int(row[3] or 0)
                        m["pgbouncer_sv_active"] = int(row[4] or 0)
                        m["pgbouncer_sv_idle"] = int(row[5] or 0)
                        break

    labels = f'sandbox_id="{SANDBOX_ID}",template="{TEMPLATE_ID}",module="{MODULE_ID}"'
    lines = [
        "# HELP crucible_vm_memory_used_mb Live Firecracker KVM memory usage in MB",
        "# TYPE crucible_vm_memory_used_mb gauge",
        f"crucible_vm_memory_used_mb{{{labels}}} {m['crucible_vm_memory_used_mb']}",
        "# HELP linux_loadavg_1m Kernel 1-minute load average inside Firecracker VM",
        "# TYPE linux_loadavg_1m gauge",
        f"linux_loadavg_1m{{{labels}}} {m['linux_loadavg_1m']}",
        "# HELP linux_open_fds Allocated kernel file descriptors",
        "# TYPE linux_open_fds gauge",
        f"linux_open_fds{{{labels}}} {m['linux_open_fds']}",
        "# HELP pg_orders_seq_scans Cumulative PostgreSQL sequential scans on orders table",
        "# TYPE pg_orders_seq_scans counter",
        f"pg_orders_seq_scans{{{labels}}} {m['pg_orders_seq_scans']}",
        "# HELP pg_orders_idx_scans Cumulative PostgreSQL index scans on orders table",
        "# TYPE pg_orders_idx_scans counter",
        f"pg_orders_idx_scans{{{labels}}} {m['pg_orders_idx_scans']}",
        "# HELP pg_orders_dead_tuples PostgreSQL MVCC dead tuples awaiting VACUUM on orders",
        "# TYPE pg_orders_dead_tuples gauge",
        f"pg_orders_dead_tuples{{{labels}}} {m['pg_orders_dead_tuples']}",
        "# HELP pg_waiting_locks Active PostgreSQL queries blocked on Lock wait events",
        "# TYPE pg_waiting_locks gauge",
        f"pg_waiting_locks{{{labels}}} {m['pg_waiting_locks']}",
        "# HELP pgbouncer_cl_waiting Client connections waiting in PgBouncer pool queue",
        "# TYPE pgbouncer_cl_waiting gauge",
        f"pgbouncer_cl_waiting{{{labels}}} {m['pgbouncer_cl_waiting']}",
        "# HELP pgbouncer_sv_active Active PgBouncer server backend connections",
        "# TYPE pgbouncer_sv_active gauge",
        f"pgbouncer_sv_active{{{labels}}} {m['pgbouncer_sv_active']}",
        "# HELP crucible_sla_latency_ms End-to-end SLA probe latency in milliseconds",
        "# TYPE crucible_sla_latency_ms gauge",
        f"crucible_sla_latency_ms{{{labels}}} {m['crucible_sla_latency_ms']}",
    ]
    return m, "\n".join(lines) + "\n"


class ExtendTtlRequest(BaseModel):
    expires_epoch: int = Field(..., ge=1)


@app.post("/internal/extend", dependencies=[Depends(_require_vm_secret)])
def internal_extend(req: ExtendTtlRequest) -> dict[str, Any]:
    _state["last_activity"] = time.time()
    current = int(_state.get("expires_epoch", EXPIRES_EPOCH))
    updated = max(current, int(req.expires_epoch))
    _state["expires_epoch"] = updated
    return {
        "ok": True,
        "expires_epoch": updated,
        "ttl_remaining_seconds": max(0, int(updated - time.time())),
    }


@app.get("/internal/metrics", dependencies=[Depends(_require_vm_secret)])
def internal_metrics() -> dict[str, Any]:
    # Do NOT reset _state["last_activity"] on background metrics polling so truly idle VMs
    # cleanly auto-reap after IDLE_TIMEOUT_SECONDS instead of burning idle compute.
    mem_used_mb = 0
    mem_total_mb = 0
    with contextlib.suppress(OSError):
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                info[parts[0].rstrip(":")] = int(parts[1])
        mem_total_mb = info.get("MemTotal", 0) // 1024
        avail = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
        mem_used_mb = max(0, mem_total_mb - avail)

    daemons = collect_live_daemons()
    telemetry = probe_live_telemetry(WORKSPACE_DIR, TEMPLATE_ID)
    prom_map, prom_text = _collect_live_prometheus_scrape(mem_used_mb, mem_total_mb, daemons, telemetry)
    return {
        "sandbox_id": SANDBOX_ID,
        "template_id": TEMPLATE_ID,
        "module": MODULE_ID,
        "backend": "fly-firecracker",
        "real_daemons": has_real_postgres() or has_real_nginx(),
        "daemons": daemons,
        "uptime_seconds": round(time.time() - BOOT_EPOCH, 1),
        "ttl_remaining_seconds": max(0, int(EXPIRES_EPOCH - time.time())),
        "active_terminals": _state["active_ws"],
        "memory_used_mb": mem_used_mb,
        "memory_total_mb": mem_total_mb,
        "fault_armed": _state["fault_armed"],
        "active_scenario_id": _state.get("active_scenario_id"),
        "loadgen": _loadgen_snapshot(),
        "telemetry": telemetry,
        "prometheus": prom_map,
        "prometheus_text": prom_text,
    }


@app.get("/internal/metrics/prometheus", dependencies=[Depends(_require_vm_secret)])
def internal_metrics_prometheus() -> PlainTextResponse:
    snap = internal_metrics()
    return PlainTextResponse(
        content=str(snap.get("prometheus_text", "")),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/internal/files", dependencies=[Depends(_require_vm_secret)])
def internal_list_files() -> dict[str, Any]:
    _state["last_activity"] = time.time()
    return {"files": list_editable_files(WORKSPACE_DIR)}


@app.get("/internal/files/read", dependencies=[Depends(_require_vm_secret)])
def internal_read_file(path: str = Query(..., min_length=1, max_length=200)) -> dict[str, Any]:
    _state["last_activity"] = time.time()
    try:
        return read_workspace_file(WORKSPACE_DIR, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.put("/internal/files/write", dependencies=[Depends(_require_vm_secret)])
def internal_write_file(req: WriteFileRequest) -> dict[str, Any]:
    _state["last_activity"] = time.time()
    try:
        res = write_workspace_file(WORKSPACE_DIR, req.path, req.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    reload_res = reload_lab_daemon(WORKSPACE_DIR, TEMPLATE_ID) if req.reload else None
    telemetry = probe_live_telemetry(WORKSPACE_DIR, TEMPLATE_ID)
    return {**res, "reload": reload_res, "telemetry": telemetry}


@app.post("/internal/chaos", dependencies=[Depends(_require_vm_secret)])
def internal_chaos(body: ChaosBody | None = None) -> dict[str, Any]:
    _state["last_activity"] = time.time()
    fault = arm_scenario_fault(
        WORKSPACE_DIR,
        TEMPLATE_ID,
        SANDBOX_ID,
        scenario_id=body.scenario_id if body else None,
        seed=body.seed if body else None,
    )
    _state["fault_armed"] = True
    _state["active_scenario_id"] = fault.fault_id
    return {
        "fault_id": fault.fault_id,
        "symptom": fault.symptom,
        "remediation_hint": fault.remediation_hint,
    }


@app.post("/internal/loadgen", dependencies=[Depends(_require_vm_secret)])
async def internal_loadgen(body: LoadgenBody) -> dict[str, Any]:
    _state["last_activity"] = time.time()
    existing = _loadgen.get("task")
    if existing is not None and not existing.done():
        _loadgen["active"] = False
        existing.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await existing
    if body.enabled:
        _loadgen["task"] = asyncio.create_task(_run_loadgen_loop(body.rps, body.duration_s))
        await asyncio.sleep(0.05)
    return {"ok": True, "loadgen": _loadgen_snapshot()}


@app.post("/internal/project/scaffold", dependencies=[Depends(_require_vm_secret)])
def internal_project_scaffold(body: ProjectActionBody) -> dict[str, Any]:
    _state["last_activity"] = time.time()
    try:
        return scaffold_workspace_project(
            WORKSPACE_DIR,
            body.project_id,
            use_reference=body.use_reference,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/internal/project/test", dependencies=[Depends(_require_vm_secret)])
def internal_project_test(body: ProjectActionBody) -> dict[str, Any]:
    _state["last_activity"] = time.time()
    try:
        return test_workspace_project(WORKSPACE_DIR, body.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/internal/verify", dependencies=[Depends(_require_vm_secret)])
def internal_verify() -> dict[str, Any]:
    _state["last_activity"] = time.time()
    ok, detail, checks = verify_workspace_checks(WORKSPACE_DIR, TEMPLATE_ID)
    if ok:
        _state["fault_armed"] = False
    return {
        "passed": ok,
        "detail": detail,
        "checks": checks,
        "daemons": collect_live_daemons(),
    }


@app.websocket("/internal/terminal")
async def internal_terminal(
    websocket: WebSocket,
    token: str = Query(default=""),
) -> None:
    if _verify_token(token) is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    _state["active_ws"] += 1
    _state["last_activity"] = time.time()

    master_fd, slave_fd = pty.openpty()

    def _set_winsize(fd: int, cols: int, rows: int) -> None:
        c = max(40, min(260, cols))
        r = max(12, min(100, rows))
        with contextlib.suppress(OSError):
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", r, c, 0, 0))

    _set_winsize(master_fd, 120, 32)

    clean_env = {
        "PATH": f"{WORKSPACE_DIR / 'bin'}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(WORKSPACE_DIR),
        "USER": "operator",
        "LOGNAME": "operator",
        "TERM": "xterm-256color",
        "LANG": "C.UTF-8",
        "PS1": f"\\[\\e[1;92m\\]operator@{TEMPLATE_ID}\\[\\e[0m\\]:\\[\\e[1;36m\\]\\w\\[\\e[0m\\]\\$ ",
        "SPARTAN_SANDBOX_ID": SANDBOX_ID,
        "SPARTAN_TEMPLATE": TEMPLATE_ID,
        "SPARTAN_MODULE": MODULE_ID,
    }

    op_uid: int | None = None
    op_gid: int | None = None
    if os.geteuid() == 0:
        with contextlib.suppress(KeyError):
            pw = pwd.getpwnam("operator")
            op_uid, op_gid = pw.pw_uid, pw.pw_gid
            with contextlib.suppress(OSError):
                os.fchown(slave_fd, op_uid, op_gid)

    def _sandbox_preexec() -> None:
        os.setsid()
        with contextlib.suppress(OSError):
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        with contextlib.suppress(OSError, ValueError):
            resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
        with contextlib.suppress(OSError, ValueError):
            resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024 * 1024, 128 * 1024 * 1024))
        with contextlib.suppress(OSError, ValueError):
            resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
        if op_uid is not None and op_gid is not None:
            os.initgroups("operator", op_gid)
            os.setgid(op_gid)
            os.setuid(op_uid)

    use_tmux = bool(shutil.which("tmux"))
    shell_bin = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
    if use_tmux:
        shell_args = ["tmux", "new-session", "-A", "-s", "crucible"]
    else:
        shell_args = [shell_bin, "--noprofile", "--norc", "-i"] if shell_bin.endswith("bash") else [shell_bin, "-i"]
    proc = subprocess.Popen(
        shell_args,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(WORKSPACE_DIR),
        env=clean_env,
        preexec_fn=_sandbox_preexec,
        close_fds=True,
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)

    loop = asyncio.get_running_loop()
    out_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)

    def _on_pty_readable() -> None:
        try:
            chunk = os.read(master_fd, 4096)
            if chunk:
                with contextlib.suppress(asyncio.QueueFull):
                    out_queue.put_nowait(chunk)
            else:
                with contextlib.suppress(asyncio.QueueFull):
                    out_queue.put_nowait(None)
        except BlockingIOError:
            return
        except OSError:
            with contextlib.suppress(asyncio.QueueFull):
                out_queue.put_nowait(None)

    loop.add_reader(master_fd, _on_pty_readable)

    daemons = [k for k, up in collect_live_daemons().items() if up]
    daemon_str = ", ".join(daemons) if daemons else "linux-shell"
    banner = (
        f"\x1b[1;92m[crucible-firecracker-kvm]\x1b[0m Dedicated MicroVM · "
        f"{SANDBOX_ID} ({TEMPLATE_ID} · {MODULE_ID}) · {'tmux persistent session' if use_tmux else 'live PTY'}\r\n"
        f"\x1b[36mLive Services:\x1b[0m {daemon_str} · \x1b[36mTip:\x1b[0m use "
        f"\x1b[1;33mLive Files\x1b[0m tab or run \x1b[1;33mcat README.md\x1b[0m\r\n"
    )
    await websocket.send_text(banner)

    async def _pump_pty_to_ws() -> None:
        while True:
            chunk = await out_queue.get()
            if chunk is None:
                break
            await websocket.send_text(chunk.decode("utf-8", errors="replace"))

    async def _push_metrics_over_ws() -> None:
        """Push telemetry every 6s over the existing WS to eliminate 3s Vercel/Supabase polling."""
        while True:
            await asyncio.sleep(6.0)
            try:
                snap = await asyncio.to_thread(internal_metrics)
                await websocket.send_text(json.dumps({"type": "metrics", "data": snap}))
            except Exception:
                break

    reader_task = asyncio.create_task(_pump_pty_to_ws())
    metrics_task = asyncio.create_task(_push_metrics_over_ws())
    try:
        while True:
            raw = await websocket.receive_text()
            _state["last_activity"] = time.time()
            data_to_write = raw
            if raw.startswith("{"):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        msg_type = parsed.get("type")
                        if msg_type == "ping":
                            await websocket.send_text(json.dumps({"type": "pong", "ts": int(time.time())}))
                            continue
                        if msg_type == "resize":
                            _set_winsize(
                                master_fd,
                                int(parsed.get("cols", 120)),
                                int(parsed.get("rows", 32)),
                            )
                            continue
                        if msg_type == "input" and isinstance(parsed.get("data"), str):
                            data_to_write = parsed["data"]
                except (ValueError, TypeError):
                    pass
            if data_to_write:
                os.write(master_fd, data_to_write.encode("utf-8", errors="ignore"))
    except (WebSocketDisconnect, OSError):
        pass
    finally:
        _state["active_ws"] = max(0, _state["active_ws"] - 1)
        _state["last_activity"] = time.time()
        with contextlib.suppress(Exception):
            loop.remove_reader(master_fd)
        reader_task.cancel()
        metrics_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader_task
        with contextlib.suppress(asyncio.CancelledError):
            await metrics_task
        with contextlib.suppress(OSError):
            os.close(master_fd)
        # When tmux is active, only terminate the attached client (preserving the tmux server & user shell
        # across browser refreshes and Wi-Fi drops!). Without tmux, clean up the process group as before.
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                if use_tmux:
                    proc.terminate()
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)
            if proc.poll() is None:
                with contextlib.suppress(OSError):
                    if use_tmux:
                        proc.kill()
                    else:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
