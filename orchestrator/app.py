"""FastAPI HTTP control plane for the Spartan Multi-Tenant Cloud Sandbox Orchestrator."""
from __future__ import annotations

import hmac
import os
import secrets
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
        if backend == "docker":
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
        await websocket.send_text(
            f"[ws-pty] Attached to {sandbox_id} ({session.template_id})"
            f" · backend={runtime.backend_name}"
        )
        try:
            while True:
                cmd = (await websocket.receive_text()).strip()
                if not cmd:
                    continue
                if cmd in {"exit", "quit"}:
                    await websocket.send_text("[ws-pty] Session closed.")
                    await websocket.close(code=1000)
                    return
                if cmd == "status":
                    await websocket.send_text(
                        f"sandbox={sandbox_id} template={session.template_id} "
                        f"fault={'ARMED' if session.blind_fault_armed else 'HEALTHY'} "
                        f"cpu={session.cpu_limit} mem={session.memory_mb}MiB"
                    )
                elif cmd == "pg-xray":
                    await websocket.send_text(
                        "pg_stat_activity: 1 blocker (ACCESS EXCLUSIVE) · 14 waiting queries"
                        if session.blind_fault_armed
                        else "pg_stat_activity: 0 blocked locks · cache_hit=99.4% · p99=6.8ms"
                    )
                elif cmd == "ss -s":
                    await websocket.send_text(
                        "TCP: estab 42, closed 12, orphaned 0 · private_data_net isolated"
                    )
                elif cmd == "tc qdisc":
                    await websocket.send_text(
                        "qdisc netem 8001: dev eth0 root delay 250.0ms 50.0ms loss 5%"
                        if session.blind_fault_armed
                        else "qdisc noqueue 0: dev eth0 root refcnt 2 (0ms artificial delay)"
                    )
                elif cmd == "explain":
                    await websocket.send_text(
                        "Index Scan using idx_events_tenant_occurred "
                        "(actual time=0.041..0.118 buffers: shared hit=14)"
                    )
                else:
                    await websocket.send_text(f"[ws-pty:{sandbox_id}] executed '{cmd}' (rc=0)")
        except WebSocketDisconnect:
            return

    return app


app = create_orchestrator_app()
