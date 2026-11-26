"""FastAPI Stateless Control Plane for Crucible Hardware-Isolated Firecracker Sandboxes."""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hmac
import json
import os
import pty
import resource
import secrets
import signal
import struct
import subprocess
import sys
import termios
import time
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from orchestrator.build_projects import list_build_projects
from orchestrator.grader import list_all_scenarios
from orchestrator.models import (
    LAB_TEMPLATES,
    TIER_QUOTAS,
    ChaosInjectRequest,
    ChaosInjectResponse,
    ProvisionRequest,
    SandboxSession,
    VerifySandboxRequest,
    VerifySandboxResponse,
)
from orchestrator.runtime import (
    DockerSandboxRuntime,
    FlyMachinesRuntime,
    LinuxPtySandboxRuntime,
    MemorySandboxRuntime,
    SandboxRuntime,
)
from orchestrator.service import (
    QuotaExceededError,
    SandboxAccessDeniedError,
    SandboxNotFoundError,
    SandboxOrchestratorService,
)
from orchestrator.store import InMemorySessionStore, SessionStore, SupabaseSessionStore


class SandboxWriteFileBody(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=64)
    user_id: str = Field(..., min_length=2, max_length=128)
    path: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., max_length=262144)
    reload: bool = False


class SandboxLoadgenBody(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=64)
    user_id: str = Field(..., min_length=2, max_length=128)
    enabled: bool = True
    rps: int = Field(default=50, ge=1, le=50)
    duration_s: int = Field(default=60, ge=5, le=90)


class SandboxProjectBody(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=64)
    user_id: str = Field(..., min_length=2, max_length=128)
    action: str = Field(..., pattern=r"^(scaffold|test)$")
    project_id: str = Field(..., min_length=3, max_length=64)
    use_reference: bool = False


def create_orchestrator_app(
    *,
    api_key: str | None = None,
    signing_secret: str | None = None,
    runtime: SandboxRuntime | None = None,
    ws_base_url: str | None = None,
    store: SessionStore | None = None,
) -> FastAPI:
    resolved_key = (
        api_key
        if api_key is not None
        else os.environ.get("SPARTAN_ORCHESTRATOR_API_KEY", "").strip()
    )
    resolved_secret = (
        signing_secret
        if signing_secret is not None
        else os.environ.get("SPARTAN_TERMINAL_SIGNING_SECRET", "").strip()
        or secrets.token_urlsafe(32)
    )
    if runtime is None:
        backend = os.environ.get("SPARTAN_SANDBOX_BACKEND", "memory").strip().lower()
        if backend == "linux-pty":
            runtime = LinuxPtySandboxRuntime()
        elif backend == "docker":
            runtime = DockerSandboxRuntime()
        elif backend == "fly":
            runtime = FlyMachinesRuntime(
                app_name=os.environ.get("FLY_SANDBOX_APP_NAME", "crucible-sandboxes").strip(),
                api_token=os.environ.get("FLY_API_TOKEN", "").strip(),
                region=os.environ.get("FLY_SANDBOX_REGION", "iad").strip() or "iad",
                image_override=os.environ.get("FLY_SANDBOX_IMAGE", "").strip(),
                warm_pool_size=max(0, min(25, int(os.environ.get("FLY_WARM_POOL_SIZE", "0") or "0"))),
            )
        else:
            runtime = MemorySandboxRuntime()

    resolved_store = store
    if resolved_store is None:
        sb_url = os.environ.get("SUPABASE_URL", "").strip()
        sb_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if sb_url and sb_key and runtime.backend_name == "fly":
            resolved_store = SupabaseSessionStore(supabase_url=sb_url, service_role_key=sb_key)
        else:
            resolved_store = InMemorySessionStore()

    service = SandboxOrchestratorService(
        runtime=runtime,
        signing_secret=resolved_secret,
        ws_base_url=ws_base_url
        or os.environ.get("SPARTAN_TERMINAL_WS_URL", "wss://sandbox.sageideas.dev/ws"),
        store=resolved_store,
    )

    @contextlib.asynccontextmanager
    async def _lifespan(_app: FastAPI):
        stop_event = asyncio.Event()

        async def _reaper_worker() -> None:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=30.0)
                    break
                except asyncio.TimeoutError:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(service.reap_expired)

        task = asyncio.create_task(_reaper_worker())
        try:
            yield
        finally:
            stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    app = FastAPI(
        title="Crucible Cloud Sandbox Orchestrator",
        version="2.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.orchestrator = service

    def require_api_key(
        x_spartan_orchestrator_key: str | None = Header(default=None),
    ) -> None:
        if not resolved_key:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator API key not configured (fail-closed).",
            )
        if not x_spartan_orchestrator_key or not hmac.compare_digest(
            x_spartan_orchestrator_key, resolved_key
        ):
            raise HTTPException(status_code=401, detail="Invalid orchestrator API key.")

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "backend": runtime.backend_name,
            "store": service.store_name,
            "isolation": "kvm-firecracker-microvm" if runtime.backend_name == "fly" else runtime.backend_name,
            "activeSandboxes": service.active_count(),
        }

    @app.get("/v1/templates", dependencies=[Depends(require_api_key)])
    def list_templates() -> dict[str, Any]:
        return {
            "templates": [t.model_dump() for t in LAB_TEMPLATES.values()],
            "quotas": {
                k: {
                    "max_concurrent": q.max_concurrent,
                    "ttl_minutes": q.ttl_minutes,
                    "cpu_limit": q.cpu_limit,
                    "memory_mb": q.memory_mb,
                    "pids_limit": q.pids_limit,
                }
                for k, q in TIER_QUOTAS.items()
            },
        }

    @app.post(
        "/v1/sandboxes",
        response_model=SandboxSession,
        dependencies=[Depends(require_api_key)],
    )
    def provision_sandbox(req: ProvisionRequest) -> SandboxSession:
        try:
            return service.provision(req)
        except QuotaExceededError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None

    @app.get("/v1/sandboxes", dependencies=[Depends(require_api_key)])
    def list_sandboxes(
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
    ) -> dict[str, Any]:
        items = service.list_user_sandboxes(tenant_id=tenant_id, user_id=user_id)
        return {"sandboxes": [s.model_dump() for s in items]}

    @app.get(
        "/v1/sandboxes/{sandbox_id}",
        response_model=SandboxSession,
        dependencies=[Depends(require_api_key)],
    )
    def get_sandbox(
        sandbox_id: str,
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
    ) -> SandboxSession:
        try:
            return service.get_sandbox(
                sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @app.get("/v1/sandboxes/{sandbox_id}/metrics", dependencies=[Depends(require_api_key)])
    def sandbox_metrics(
        sandbox_id: str,
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
    ) -> dict[str, Any]:
        try:
            return service.get_metrics(
                sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @app.get("/v1/sandboxes/{sandbox_id}/metrics/prometheus", dependencies=[Depends(require_api_key)])
    def sandbox_metrics_prometheus(
        sandbox_id: str,
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
    ) -> PlainTextResponse:
        try:
            snap = service.get_metrics(
                sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        prom_text = snap.get("prometheus_text")
        if not isinstance(prom_text, str) or not prom_text.strip():
            tel = snap.get("telemetry") if isinstance(snap.get("telemetry"), dict) else {}
            prom_text = (
                "# HELP crucible_sla_latency_ms End-to-end SLA probe latency in milliseconds\n"
                "# TYPE crucible_sla_latency_ms gauge\n"
                f'crucible_sla_latency_ms{{sandbox_id="{sandbox_id}"}} {tel.get("latency_ms", 0)}\n'
            )
        return PlainTextResponse(
            content=prom_text,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/v1/sandboxes/{sandbox_id}/files", dependencies=[Depends(require_api_key)])
    def list_sandbox_files(
        sandbox_id: str,
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
    ) -> dict[str, Any]:
        try:
            files = service.list_files(sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id)
            return {"files": files}
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @app.get("/v1/sandboxes/{sandbox_id}/files/read", dependencies=[Depends(require_api_key)])
    def read_sandbox_file(
        sandbox_id: str,
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
        path: str = Query(..., min_length=1, max_length=200),
    ) -> dict[str, Any]:
        try:
            return service.read_file(sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id, path=path)
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.put("/v1/sandboxes/{sandbox_id}/files/write", dependencies=[Depends(require_api_key)])
    def write_sandbox_file(sandbox_id: str, req: SandboxWriteFileBody) -> dict[str, Any]:
        try:
            return service.write_file(
                sandbox_id=sandbox_id,
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                path=req.path,
                content=req.content,
                reload=req.reload,
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/v1/scenarios", dependencies=[Depends(require_api_key)])
    def list_scenarios_and_projects() -> dict[str, Any]:
        return {
            "scenarios": list_all_scenarios(),
            "projects": list_build_projects(),
        }

    @app.post(
        "/v1/sandboxes/{sandbox_id}/chaos",
        response_model=ChaosInjectResponse,
        dependencies=[Depends(require_api_key)],
    )
    def inject_chaos(sandbox_id: str, req: ChaosInjectRequest) -> ChaosInjectResponse:
        try:
            return service.inject_blind_fault(
                sandbox_id=sandbox_id,
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                seed=req.seed,
                scenario_id=req.scenario_id,
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None

    @app.post("/v1/sandboxes/{sandbox_id}/loadgen", dependencies=[Depends(require_api_key)])
    def sandbox_loadgen(sandbox_id: str, req: SandboxLoadgenBody) -> dict[str, Any]:
        try:
            return service.control_loadgen(
                sandbox_id=sandbox_id,
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                enabled=req.enabled,
                rps=req.rps,
                duration_s=req.duration_s,
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None

    @app.post("/v1/sandboxes/{sandbox_id}/project", dependencies=[Depends(require_api_key)])
    def sandbox_project_action(sandbox_id: str, req: SandboxProjectBody) -> dict[str, Any]:
        try:
            return service.run_project_action(
                sandbox_id=sandbox_id,
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                action=req.action,
                project_id=req.project_id,
                use_reference=req.use_reference,
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None

    @app.post(
        "/v1/sandboxes/{sandbox_id}/verify",
        response_model=VerifySandboxResponse,
        dependencies=[Depends(require_api_key)],
    )
    def verify_sandbox(sandbox_id: str, req: VerifySandboxRequest) -> VerifySandboxResponse:
        try:
            return service.verify_and_issue_receipt(
                sandbox_id=sandbox_id, tenant_id=req.tenant_id, user_id=req.user_id
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @app.delete(
        "/v1/sandboxes/{sandbox_id}",
        response_model=SandboxSession,
        dependencies=[Depends(require_api_key)],
    )
    def terminate_sandbox(
        sandbox_id: str,
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
    ) -> SandboxSession:
        try:
            return service.terminate(
                sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @app.post("/v1/admin/reap", dependencies=[Depends(require_api_key)])
    def reap_sandboxes() -> dict[str, Any]:
        reaped = service.reap_expired()
        return {"reaped": reaped, "activeSandboxes": service.active_count()}

    @app.post("/v1/admin/warm-pool", dependencies=[Depends(require_api_key)])
    def replenish_warm_pool(target_size: int | None = Query(default=None, ge=0, le=25)) -> dict[str, Any]:
        if isinstance(runtime, FlyMachinesRuntime):
            return runtime.ensure_warm_pool(target_size=target_size)
        return {"desired": 0, "ready": 0, "created": 0, "backend": runtime.backend_name}

    @app.get("/v1/admin/sandboxes", dependencies=[Depends(require_api_key)])
    def admin_list_sandboxes() -> dict[str, Any]:
        active = service.list_all_active()
        return {
            "backend": runtime.backend_name,
            "store": service.store_name,
            "activeSandboxes": len(active),
            "sandboxes": [s.model_dump() for s in active],
        }

    @app.delete(
        "/v1/admin/sandboxes/{sandbox_id}",
        response_model=SandboxSession,
        dependencies=[Depends(require_api_key)],
    )
    def admin_kill_sandbox(sandbox_id: str) -> SandboxSession:
        try:
            return service.admin_force_terminate(sandbox_id=sandbox_id)
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.post(
        "/v1/sandboxes/{sandbox_id}/terminal-token",
        dependencies=[Depends(require_api_key)],
    )
    def issue_terminal_token(
        sandbox_id: str,
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
    ) -> dict[str, Any]:
        try:
            return service.issue_terminal_token(
                sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @app.post(
        "/v1/sandboxes/{sandbox_id}/extend",
        dependencies=[Depends(require_api_key)],
    )
    def extend_sandbox(
        sandbox_id: str,
        tenant_id: str = Query(..., min_length=2, max_length=64),
        user_id: str = Query(..., min_length=2, max_length=128),
        extra_minutes: int = Query(default=60, ge=15, le=60),
    ) -> dict[str, Any]:
        try:
            return service.extend_sandbox(
                sandbox_id=sandbox_id,
                tenant_id=tenant_id,
                user_id=user_id,
                extra_minutes=extra_minutes,
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @app.websocket("/v1/sandboxes/{sandbox_id}/terminal")
    async def sandbox_terminal(
        websocket: WebSocket,
        sandbox_id: str,
        token: str = Query(default=""),
    ) -> None:
        rec = await asyncio.to_thread(
            service.authenticate_terminal_record, sandbox_id=sandbox_id, token=token
        )
        if rec is None:
            await websocket.close(code=4401)
            return

        await websocket.accept()

        # 1. Production Firecracker KVM MicroVM: private 6pn WireGuard WebSocket tunnel
        if isinstance(runtime, FlyMachinesRuntime) and rec.fly_machine_id:
            import websockets  # type: ignore[import-untyped]

            vm_ws_url = (
                f"{runtime.get_internal_ws_url(machine_id=rec.fly_machine_id, private_ip=rec.private_ip)}"
                f"?token={urllib.parse.quote(token, safe='')}"
            )
            try:
                async with websockets.connect(
                    vm_ws_url,
                    open_timeout=10,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2 * 1024 * 1024,
                ) as vm_ws:

                    async def _client_to_vm() -> None:
                        while True:
                            msg = await websocket.receive_text()
                            await vm_ws.send(msg)

                    async def _vm_to_client() -> None:
                        async for msg in vm_ws:
                            if isinstance(msg, bytes):
                                await websocket.send_text(msg.decode("utf-8", errors="replace"))
                            else:
                                await websocket.send_text(msg)

                    t1 = asyncio.create_task(_client_to_vm())
                    t2 = asyncio.create_task(_vm_to_client())
                    done, pending = await asyncio.wait(
                        {t1, t2}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for p in pending:
                        p.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await p
                    for d in done:
                        with contextlib.suppress(WebSocketDisconnect, Exception):
                            d.result()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await websocket.send_text(
                        f"\r\n\x1b[1;31m[crucible-firecracker] MicroVM terminal disconnected: {exc}\x1b[0m\r\n"
                    )
                    await websocket.close(code=1011)
            return

        # 2. Local Dev/CI Linux PTY Shell (with hardened rlimits + ping/pong heartbeat)
        get_ws = getattr(runtime, "get_workspace_dir", None)
        ws_dir: Path | None = (
            get_ws(container_name=rec.container_name) if callable(get_ws) else None
        )
        if ws_dir is not None and ws_dir.exists():
            master_fd, slave_fd = pty.openpty()

            def _set_winsize(fd: int, cols: int, rows: int) -> None:
                c = max(40, min(260, cols))
                r = max(12, min(100, rows))
                with contextlib.suppress(OSError):
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", r, c, 0, 0))

            _set_winsize(master_fd, 120, 32)

            clean_env = {
                "PATH": f"{ws_dir / 'bin'}:/usr/local/bin:/usr/bin:/bin",
                "HOME": str(ws_dir),
                "TERM": "xterm-256color",
                "LANG": "C.UTF-8",
                "PS1": f"\\[\\e[1;92m\\]operator@{rec.template_id}\\[\\e[0m\\]:\\[\\e[1;36m\\]\\w\\[\\e[0m\\]\\$ ",
                "SPARTAN_SANDBOX_ID": sandbox_id,
                "SPARTAN_TEMPLATE": rec.template_id,
                "SPARTAN_MODULE": rec.module_id,
            }

            def _sandbox_preexec() -> None:
                os.setsid()
                with contextlib.suppress(OSError):
                    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                with contextlib.suppress(OSError, ValueError):
                    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
                with contextlib.suppress(OSError, ValueError):
                    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
                if sys.platform.startswith("linux"):
                    with contextlib.suppress(OSError, ValueError):
                        resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))

            shell_bin = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
            shell_args = [shell_bin, "--noprofile", "--norc", "-i"] if shell_bin.endswith("bash") else [shell_bin, "-i"]
            proc = subprocess.Popen(
                shell_args,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(ws_dir),
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

            banner = (
                f"\x1b[1;92m[crucible-linux-pty]\x1b[0m Attached to real Linux shell · "
                f"{sandbox_id} ({rec.template_id} · {rec.module_id})\r\n"
                f"\x1b[36mTip:\x1b[0m Run \x1b[1;33mcat README.md\x1b[0m, \x1b[1;33mls -la\x1b[0m, "
                f"or \x1b[1;33mhint\x1b[0m\r\n"
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
                    data_to_write = raw
                    if raw.startswith("{"):
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                if parsed.get("type") == "ping":
                                    await websocket.send_text(json.dumps({"type": "pong", "ts": int(time.time())}))
                                    continue
                                if parsed.get("type") == "resize":
                                    _set_winsize(
                                        master_fd,
                                        int(parsed.get("cols", 120)),
                                        int(parsed.get("rows", 32)),
                                    )
                                    continue
                                if parsed.get("type") == "input" and isinstance(parsed.get("data"), str):
                                    data_to_write = parsed["data"]
                        except (ValueError, TypeError):
                            pass
                    if data_to_write:
                        os.write(master_fd, data_to_write.encode("utf-8", errors="ignore"))
            except (WebSocketDisconnect, OSError):
                pass
            finally:
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
            return

        # 3. Deterministic memory-runtime fallback for CI unit tests only
        await websocket.send_text(
            f"[ws-pty] Attached to {sandbox_id} ({rec.template_id}) · backend={runtime.backend_name}\r\n"
        )
        try:
            while True:
                cmd = (await websocket.receive_text()).strip()
                if not cmd:
                    continue
                if cmd in {"exit", "quit"}:
                    await websocket.send_text("[ws-pty] Session closed.\r\n")
                    await websocket.close(code=1000)
                    return
                await websocket.send_text(f"[memory-ci:{sandbox_id}] {cmd}\r\n")
        except WebSocketDisconnect:
            return

    return app


app = create_orchestrator_app()
