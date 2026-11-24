"""FastAPI HTTP control plane for the Spartan Multi-Tenant Cloud Sandbox Orchestrator."""
from __future__ import annotations

import hmac
import os
import secrets
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query

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
from orchestrator.runtime import DockerSandboxRuntime, MemorySandboxRuntime, SandboxRuntime
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
        runtime = DockerSandboxRuntime() if backend == "docker" else MemorySandboxRuntime()

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

    return app


app = create_orchestrator_app()
