"""Multi-tenant sandbox lifecycle service: quotas, IDOR guards, TTL janitor & receipts."""
from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from orchestrator.models import (
    LAB_TEMPLATES,
    TIER_QUOTAS,
    ChaosInjectResponse,
    ProvisionRequest,
    SandboxSession,
    VerifySandboxResponse,
)
from orchestrator.runtime import (
    SandboxRuntime,
    create_terminal_token,
    security_profile_summary,
)
from tools.war_room import ChaosFault, compute_receipt_sha256, select_blind_fault


class QuotaExceededError(Exception):
    pass


class SandboxNotFoundError(Exception):
    pass


class SandboxAccessDeniedError(Exception):
    pass


@dataclass
class _SandboxRecord:
    session: SandboxSession
    created_epoch: float
    expires_epoch: int
    secret_fault: ChaosFault | None = None
    fault_started_epoch: float | None = None


class SandboxOrchestratorService:
    def __init__(
        self,
        *,
        runtime: SandboxRuntime,
        signing_secret: str,
        ws_base_url: str = "wss://sandbox.sageideas.dev/ws",
    ) -> None:
        if len(signing_secret) < 16:
            raise ValueError("signing_secret must be at least 16 characters")
        self.runtime = runtime
        self._signing_secret = signing_secret
        self._ws_base_url = ws_base_url.rstrip("/")
        self._records: dict[str, _SandboxRecord] = {}

    def _now(self) -> float:
        return time.time()

    def reap_expired(self, now_epoch: float | None = None) -> list[str]:
        now = self._now() if now_epoch is None else now_epoch
        reaped: list[str] = []
        for sid, rec in list(self._records.items()):
            if rec.session.status == "running" and now >= rec.expires_epoch:
                self.runtime.stop_sandbox(
                    container_name=rec.session.container_name,
                    network_name=rec.session.network_name,
                )
                rec.session.status = "expired"
                rec.session.terminal_token = None
                reaped.append(sid)
        return reaped

    def active_count(self) -> int:
        self.reap_expired()
        return sum(1 for r in self._records.values() if r.session.status == "running")

    def authenticate_terminal(self, *, sandbox_id: str, token: str) -> SandboxSession | None:
        self.reap_expired()
        rec = self._records.get(sandbox_id)
        if (
            rec is None
            or rec.session.status != "running"
            or not token
            or not rec.session.terminal_token
            or not hmac.compare_digest(token, rec.session.terminal_token)
        ):
            return None
        return rec.session

    def list_user_sandboxes(self, *, tenant_id: str, user_id: str) -> list[SandboxSession]:
        self.reap_expired()
        return [
            r.session.model_copy(update={"terminal_token": None})
            for r in self._records.values()
            if r.session.tenant_id == tenant_id
            and r.session.user_id == user_id
            and r.session.status == "running"
        ]

    def provision(self, req: ProvisionRequest) -> SandboxSession:
        self.reap_expired()
        quota = TIER_QUOTAS[req.tier]
        active_for_user = [
            r
            for r in self._records.values()
            if r.session.tenant_id == req.tenant_id
            and r.session.user_id == req.user_id
            and r.session.status == "running"
        ]
        if len(active_for_user) >= quota.max_concurrent:
            raise QuotaExceededError(
                f"Tier '{req.tier}' allows at most {quota.max_concurrent} concurrent "
                f"sandbox(es). Terminate an active sandbox before starting a new one."
            )

        template = LAB_TEMPLATES[req.template_id]
        sandbox_id = f"sbx_{secrets.token_hex(8)}"
        container_name = f"spartan-{sandbox_id}"
        network_name = f"net-{sandbox_id}"
        now_epoch = self._now()
        expires_epoch = int(now_epoch + quota.ttl_minutes * 60)

        self.runtime.start_sandbox(
            sandbox_id=sandbox_id,
            tenant_id=req.tenant_id,
            container_name=container_name,
            network_name=network_name,
            template=template,
            quota=quota,
            expires_epoch=expires_epoch,
        )

        token = create_terminal_token(
            secret=self._signing_secret,
            sandbox_id=sandbox_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            expires_epoch=expires_epoch,
        )

        fault: ChaosFault | None = None
        if req.arm_blind_chaos:
            injector = getattr(self.runtime, "inject_fault", None)
            if callable(injector):
                real_fault = injector(container_name=container_name)
                if real_fault is not None:
                    fault = ChaosFault(
                        id=real_fault.fault_id,
                        category=template.module,
                        symptom=real_fault.symptom,
                        remediation_hint=real_fault.remediation_hint,
                    )
            if fault is None:
                fault = select_blind_fault()

        session = SandboxSession(
            sandbox_id=sandbox_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            template_id=req.template_id,
            module=template.module,
            tier=req.tier,
            status="running",
            container_name=container_name,
            network_name=network_name,
            cpu_limit=quota.cpu_limit,
            memory_mb=quota.memory_mb,
            pids_limit=quota.pids_limit,
            created_at=datetime.fromtimestamp(now_epoch, UTC).isoformat(),
            expires_at=datetime.fromtimestamp(expires_epoch, UTC).isoformat(),
            terminal_ws_url=f"{self._ws_base_url}/{sandbox_id}",
            terminal_token=token,
            blind_fault_armed=fault is not None,
            blind_symptom=fault.symptom if fault else None,
            security_profile=security_profile_summary(template, quota),
        )
        self._records[sandbox_id] = _SandboxRecord(
            session=session,
            created_epoch=now_epoch,
            expires_epoch=expires_epoch,
            secret_fault=fault,
            fault_started_epoch=now_epoch if fault else None,
        )
        return session

    def _require_owned_record(
        self, *, sandbox_id: str, tenant_id: str, user_id: str
    ) -> _SandboxRecord:
        self.reap_expired()
        rec = self._records.get(sandbox_id)
        if rec is None:
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' not found")
        if rec.session.tenant_id != tenant_id or rec.session.user_id != user_id:
            raise SandboxAccessDeniedError("Cross-tenant or cross-user sandbox access denied")
        return rec

    def get_sandbox(
        self, *, sandbox_id: str, tenant_id: str, user_id: str
    ) -> SandboxSession:
        rec = self._require_owned_record(
            sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
        )
        return rec.session.model_copy(update={"terminal_token": None})

    def inject_blind_fault(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        user_id: str,
        seed: int | None = None,
    ) -> ChaosInjectResponse:
        rec = self._require_owned_record(
            sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
        )
        if rec.session.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")
        fault: ChaosFault | None = None
        injector = getattr(self.runtime, "inject_fault", None)
        if callable(injector):
            real_fault = injector(container_name=rec.session.container_name)
            if real_fault is not None:
                fault = ChaosFault(
                    id=real_fault.fault_id,
                    category=rec.session.module,
                    symptom=real_fault.symptom,
                    remediation_hint=real_fault.remediation_hint,
                )
        if fault is None:
            fault = select_blind_fault(seed=seed)
        now = self._now()
        rec.secret_fault = fault
        rec.fault_started_epoch = now
        rec.session.blind_fault_armed = True
        rec.session.blind_symptom = fault.symptom
        return ChaosInjectResponse(
            sandbox_id=sandbox_id,
            status="armed",
            symptom=fault.symptom,
            started_at=datetime.fromtimestamp(now, UTC).isoformat(),
        )

    def verify_and_issue_receipt(
        self, *, sandbox_id: str, tenant_id: str, user_id: str
    ) -> VerifySandboxResponse:
        rec = self._require_owned_record(
            sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
        )
        if rec.session.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")

        healthy, detail = self.runtime.exec_health_probe(
            container_name=rec.session.container_name
        )
        start_ts = rec.fault_started_epoch or rec.created_epoch
        elapsed = max(0.0, round(self._now() - start_ts, 2))
        revealed = rec.secret_fault.id if (healthy and rec.secret_fault) else None
        hint = rec.secret_fault.remediation_hint if (healthy and rec.secret_fault) else None

        receipt: dict[str, Any] = {
            "schemaVersion": 1,
            "module": rec.session.module,
            "sandboxId": sandbox_id,
            "templateId": rec.session.template_id,
            "passed": healthy,
            "passedAt": datetime.now(UTC).isoformat(),
            "elapsedSeconds": elapsed,
            "checks": [
                {
                    "name": "sandbox_sla_probe",
                    "status": "pass" if healthy else "fail",
                    "detail": detail,
                }
            ],
            "verifiedSkillIds": [],
        }
        receipt["sha256"] = compute_receipt_sha256(receipt)

        if healthy:
            rec.secret_fault = None
            rec.fault_started_epoch = None
            rec.session.blind_fault_armed = False
            rec.session.blind_symptom = None

        return VerifySandboxResponse(
            sandbox_id=sandbox_id,
            passed=healthy,
            elapsed_seconds=elapsed,
            revealed_fault=revealed,
            remediation_hint=hint,
            receipt=receipt,
        )

    def terminate(self, *, sandbox_id: str, tenant_id: str, user_id: str) -> SandboxSession:
        rec = self._require_owned_record(
            sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
        )
        if rec.session.status == "running":
            self.runtime.stop_sandbox(
                container_name=rec.session.container_name,
                network_name=rec.session.network_name,
            )
            rec.session.status = "terminated"
            rec.session.terminal_token = None
        return rec.session.model_copy(update={"terminal_token": None})
