"""FastAPI HTTP control plane for the Spartan Multi-Tenant Cloud Sandbox Orchestrator."""
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
import termios
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect

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


def create_orchestrator_app(
    *,
    api_key: str | None = None,
    signing_secret: str | None = None,
    runtime: SandboxRuntime | None = None,
    ws_base_url: str | None = None,
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
            )
        else:
            runtime = MemorySandboxRuntime()

    service = SandboxOrchestratorService(
        runtime=runtime,
        signing_secret=resolved_secret,
        ws_base_url=ws_base_url
        or os.environ.get("SPARTAN_TERMINAL_WS_URL", "wss://sandbox.sageideas.dev/ws"),
    )

    app = FastAPI(
        title="Spartan Cloud Sandbox Orchestrator",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
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
            )
        except SandboxNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except SandboxAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

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

    @app.websocket("/v1/sandboxes/{sandbox_id}/terminal")
    async def sandbox_terminal(
        websocket: WebSocket,
        sandbox_id: str,
        token: str = Query(default=""),
    ) -> None:
        session = service.authenticate_terminal(sandbox_id=sandbox_id, token=token)
        if session is None:
            await websocket.close(code=4401)
            return

        await websocket.accept()

        get_ws = getattr(runtime, "get_workspace_dir", None)
        ws_dir: Path | None = (
            get_ws(container_name=session.container_name) if callable(get_ws) else None
        )

        # Real POSIX PTY shell for LinuxPtySandboxRuntime (production Firecracker MicroVM)
        if ws_dir is not None and ws_dir.exists():
            master_fd, slave_fd = pty.openpty()

            def _set_winsize(fd: int, cols: int, rows: int) -> None:
                c = max(40, min(240, cols))
                r = max(12, min(80, rows))
                with contextlib.suppress(OSError):
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", r, c, 0, 0))

            _set_winsize(master_fd, 110, 28)

            # Strictly strip all orchestrator secrets from the sandbox child environment!
            clean_env = {
                "PATH": f"{ws_dir / 'bin'}:/usr/local/bin:/usr/bin:/bin",
                "HOME": str(ws_dir),
                "TERM": "xterm-256color",
                "LANG": "C.UTF-8",
                "PS1": f"\\[\x1b[1;92m\\]operator@{session.template_id}\\[\\x1b[0m\\]:\\[\x1b[1;36m\\]\\w\\[\x1b[0m\\]\\$ ",
                "SPARTAN_SANDBOX_ID": sandbox_id,
                "SPARTAN_TEMPLATE": session.template_id,
                "SPARTAN_MODULE": session.module,
            }

            def _sandbox_preexec() -> None:
                os.setsid()
                with contextlib.suppress(OSError):
                    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                with contextlib.suppress(OSError, ValueError):
                    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
                with contextlib.suppress(OSError, ValueError):
                    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))

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
            out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

            def _on_pty_readable() -> None:
                try:
                    chunk = os.read(master_fd, 4096)
                    if chunk:
                        out_queue.put_nowait(chunk)
                    else:
                        out_queue.put_nowait(None)
                except BlockingIOError:
                    return
                except OSError:
                    out_queue.put_nowait(None)

            loop.add_reader(master_fd, _on_pty_readable)

            banner = (
                f"\x1b[1;92m[crucible-linux-pty]\x1b[0m Attached to real Linux shell · "
                f"{sandbox_id} ({session.template_id} · {session.module})\r\n"
                f"\x1b[36mTip:\x1b[0m Run \x1b[1;33mcat README.md\x1b[0m, \x1b[1;33mls -la\x1b[0m, "
                f"\x1b[1;33mcheck-sla\x1b[0m, or \x1b[1;33mhint\x1b[0m\r\n"
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
                                if parsed.get("type") == "resize":
                                    _set_winsize(
                                        master_fd,
                                        int(parsed.get("cols", 110)),
                                        int(parsed.get("rows", 28)),
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

        # Deterministic memory-runtime fallback for CI unit tests only
        await websocket.send_text(
            f"[ws-pty] Attached to {sandbox_id} ({session.template_id}) · backend={runtime.backend_name}\r\n"
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
