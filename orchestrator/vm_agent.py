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
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

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
WORKSPACE_DIR = Path(os.environ.get("SPARTAN_WORKSPACE_DIR", "/home/operator"))
BOOT_EPOCH = time.time()

_state: dict[str, Any] = {
    "ready": False,
    "active_ws": 0,
    "last_activity": time.time(),
    "fault_armed": ARM_INITIAL_FAULT,
}


class WriteFileRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., max_length=262144)
    reload: bool = False


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


def _bootstrap_lab() -> None:
    _try_harden_proc()
    provision_workspace(WORKSPACE_DIR, TEMPLATE_ID, SANDBOX_ID, arm_fault=ARM_INITIAL_FAULT)
    _state["ready"] = True


async def _idle_and_ttl_reaper() -> None:
    while True:
        await asyncio.sleep(20)
        now = time.time()
        expired = now >= EXPIRES_EPOCH
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


@app.get("/internal/metrics", dependencies=[Depends(_require_vm_secret)])
def internal_metrics() -> dict[str, Any]:
    _state["last_activity"] = time.time()
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

    telemetry = probe_live_telemetry(WORKSPACE_DIR, TEMPLATE_ID)
    return {
        "sandbox_id": SANDBOX_ID,
        "template_id": TEMPLATE_ID,
        "module": MODULE_ID,
        "backend": "fly-firecracker",
        "real_daemons": has_real_postgres() or has_real_nginx(),
        "daemons": collect_live_daemons(),
        "uptime_seconds": round(time.time() - BOOT_EPOCH, 1),
        "ttl_remaining_seconds": max(0, int(EXPIRES_EPOCH - time.time())),
        "active_terminals": _state["active_ws"],
        "memory_used_mb": mem_used_mb,
        "memory_total_mb": mem_total_mb,
        "fault_armed": _state["fault_armed"],
        "telemetry": telemetry,
    }


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
def internal_chaos() -> dict[str, Any]:
    _state["last_activity"] = time.time()
    fault = arm_scenario_fault(WORKSPACE_DIR, TEMPLATE_ID, SANDBOX_ID)
    _state["fault_armed"] = True
    return {
        "fault_id": fault.fault_id,
        "symptom": fault.symptom,
        "remediation_hint": fault.remediation_hint,
    }


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

    shell_bin = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
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
        f"{SANDBOX_ID} ({TEMPLATE_ID} · {MODULE_ID})\r\n"
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

    reader_task = asyncio.create_task(_pump_pty_to_ws())
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
        with contextlib.suppress(asyncio.CancelledError):
            await reader_task
        with contextlib.suppress(OSError):
            os.close(master_fd)
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)
            if proc.poll() is None:
                with contextlib.suppress(OSError):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
