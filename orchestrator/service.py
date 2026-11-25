"""Stateless multi-tenant sandbox lifecycle service: quotas, IDOR guards, durable store, TTL janitor & receipts."""
from __future__ import annotations

import hmac
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from orchestrator.grader import LAB_FAULTS, get_scenario_spec
from orchestrator.models import (
    LAB_TEMPLATES,
    TIER_QUOTAS,
    ChaosInjectResponse,
    ProvisionRequest,
    SandboxSession,
    VerifySandboxResponse,
)
from orchestrator.runtime import (
    FlyMachinesRuntime,
    SandboxRuntime,
    create_terminal_token,
    security_profile_summary,
)
from orchestrator.store import InMemorySessionStore, SessionStore, StoredSandboxRecord
from tools.war_room import ChaosFault, compute_receipt_sha256, select_blind_fault


class QuotaExceededError(Exception):
    pass


class SandboxNotFoundError(Exception):
    pass


class SandboxAccessDeniedError(Exception):
    pass


def _record_to_session(rec: StoredSandboxRecord, *, include_token: bool = False) -> SandboxSession:
    return SandboxSession(
        sandbox_id=rec.sandbox_id,
        tenant_id=rec.tenant_id,
        user_id=rec.user_id,
        template_id=rec.template_id,  # type: ignore[arg-type]
        module=rec.module_id,
        tier=rec.tier,  # type: ignore[arg-type]
        status=rec.status,  # type: ignore[arg-type]
        backend=rec.backend,
        fly_machine_id=rec.fly_machine_id,
        region=rec.region,
        container_name=rec.container_name,
        network_name=rec.network_name,
        cpu_limit=rec.cpu_limit,
        memory_mb=rec.memory_mb,
        pids_limit=rec.pids_limit,
        created_at=datetime.fromtimestamp(rec.created_epoch, UTC).isoformat(),
        expires_at=datetime.fromtimestamp(rec.expires_epoch, UTC).isoformat(),
        terminal_ws_url=rec.terminal_ws_url,
        terminal_token=rec.terminal_token if include_token else None,
        blind_fault_armed=rec.blind_fault_armed,
        blind_symptom=rec.blind_symptom,
        security_profile=list(rec.security_profile),
    )


class SandboxOrchestratorService:
    def __init__(
        self,
        *,
        runtime: SandboxRuntime,
        signing_secret: str,
        ws_base_url: str = "wss://sandbox.sageideas.dev/ws",
        store: SessionStore | None = None,
    ) -> None:
        if len(signing_secret) < 16:
            raise ValueError("signing_secret must be at least 16 characters")
        self.runtime = runtime
        self._signing_secret = signing_secret
        self._ws_base_url = ws_base_url.rstrip("/")
        self._store: SessionStore = store or InMemorySessionStore()

    @property
    def store_name(self) -> str:
        return getattr(self._store, "store_name", "memory")

    def _now(self) -> float:
        return time.time()

    def reap_expired(self, now_epoch: float | None = None) -> list[str]:
        now = self._now() if now_epoch is None else now_epoch
        reaped: list[str] = []
        for rec in self._store.list_running():
            if now >= rec.expires_epoch:
                self.runtime.stop_sandbox(
                    container_name=rec.container_name,
                    network_name=rec.network_name,
                    machine_id=rec.fly_machine_id,
                )
                rec.status = "expired"
                rec.terminal_token = None
                self._store.upsert(rec)
                reaped.append(rec.sandbox_id)
        return reaped

    def active_count(self) -> int:
        self.reap_expired()
        return len(self._store.list_running())

    def authenticate_terminal_record(
        self, *, sandbox_id: str, token: str
    ) -> StoredSandboxRecord | None:
        self.reap_expired()
        rec = self._store.get(sandbox_id)
        if (
            rec is None
            or rec.status != "running"
            or not token
            or not rec.terminal_token
            or not hmac.compare_digest(token, rec.terminal_token)
        ):
            return None
        return rec

    def authenticate_terminal(self, *, sandbox_id: str, token: str) -> SandboxSession | None:
        rec = self.authenticate_terminal_record(sandbox_id=sandbox_id, token=token)
        return _record_to_session(rec, include_token=True) if rec is not None else None

    def list_user_sandboxes(self, *, tenant_id: str, user_id: str) -> list[SandboxSession]:
        self.reap_expired()
        return [
            _record_to_session(r, include_token=False)
            for r in self._store.list_running(tenant_id=tenant_id, user_id=user_id)
        ]

    def list_all_active(self) -> list[SandboxSession]:
        self.reap_expired()
        return [_record_to_session(r, include_token=False) for r in self._store.list_running()]

    def provision(self, req: ProvisionRequest) -> SandboxSession:
        self.reap_expired()
        quota = TIER_QUOTAS[req.tier]
        active_for_user = self._store.list_running(
            tenant_id=req.tenant_id, user_id=req.user_id
        )
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

        # Generate a single-use per-VM secret so ZERO global secrets ever enter any Firecracker MicroVM!
        use_per_vm_secret = isinstance(self.runtime, FlyMachinesRuntime) and (
            self.runtime.http_sender is None or self.runtime.vm_http_sender is not None
        )
        vm_secret = secrets.token_urlsafe(32) if use_per_vm_secret else None

        start_kwargs: dict[str, Any] = {
            "sandbox_id": sandbox_id,
            "tenant_id": req.tenant_id,
            "container_name": container_name,
            "network_name": network_name,
            "template": template,
            "quota": quota,
            "expires_epoch": expires_epoch,
            "vm_secret": vm_secret or "",
            "arm_blind_chaos": req.arm_blind_chaos,
        }
        if req.scenario_id and self.runtime.backend_name in {"fly", "linux-pty"}:
            start_kwargs["scenario_id"] = req.scenario_id
        start_res = self.runtime.start_sandbox(**start_kwargs)
        machine_id = start_res.machine_id if start_res else None
        region = start_res.region if start_res else None
        private_ip = start_res.private_ip if start_res else None

        token_secret = vm_secret or self._signing_secret
        token = create_terminal_token(
            secret=token_secret,
            sandbox_id=sandbox_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            expires_epoch=expires_epoch,
        )

        fault: ChaosFault | None = None
        if req.arm_blind_chaos:
            # If the runtime already armed chaos during boot (Firecracker / LinuxPty), record fault metadata
            spec = get_scenario_spec(template.id, scenario_id=req.scenario_id)
            if self.runtime.backend_name in {"fly", "linux-pty"}:
                fault = ChaosFault(
                    id=spec.scenario_id,
                    category=template.module,
                    symptom=spec.symptom,
                    remediation_hint=spec.remediation_hint,
                )
            else:
                injector = getattr(self.runtime, "inject_fault", None)
                if callable(injector):
                    real_fault = injector(
                        container_name=container_name,
                        machine_id=machine_id,
                        vm_secret=vm_secret,
                    )
                    if real_fault is not None:
                        fault = ChaosFault(
                            id=real_fault.fault_id,
                            category=template.module,
                            symptom=real_fault.symptom,
                            remediation_hint=real_fault.remediation_hint,
                        )
            if fault is None:
                fault = select_blind_fault()

        rec = StoredSandboxRecord(
            sandbox_id=sandbox_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            template_id=req.template_id,
            module_id=template.module,
            tier=req.tier,
            backend=self.runtime.backend_name,
            status="running",
            container_name=container_name,
            network_name=network_name,
            fly_machine_id=machine_id,
            private_ip=private_ip,
            region=region,
            vm_secret=vm_secret,
            terminal_token=token,
            terminal_ws_url=f"{self._ws_base_url}/{sandbox_id}",
            cpu_limit=quota.cpu_limit,
            memory_mb=quota.memory_mb,
            pids_limit=quota.pids_limit,
            blind_fault_armed=fault is not None,
            blind_fault_id=fault.id if fault else None,
            blind_symptom=fault.symptom if fault else None,
            blind_remediation=fault.remediation_hint if fault else None,
            fault_started_epoch=now_epoch if fault else None,
            created_epoch=now_epoch,
            expires_epoch=expires_epoch,
            security_profile=security_profile_summary(
                template, quota, backend=self.runtime.backend_name
            ),
        )
        self._store.upsert(rec)
        return _record_to_session(rec, include_token=True)

    def _require_owned_record(
        self, *, sandbox_id: str, tenant_id: str, user_id: str
    ) -> StoredSandboxRecord:
        self.reap_expired()
        rec = self._store.get(sandbox_id)
        if rec is None:
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' not found")
        if rec.tenant_id != tenant_id or rec.user_id != user_id:
            raise SandboxAccessDeniedError("Cross-tenant or cross-user sandbox access denied")
        return rec

    def get_sandbox(
        self, *, sandbox_id: str, tenant_id: str, user_id: str
    ) -> SandboxSession:
        rec = self._require_owned_record(
            sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
        )
        return _record_to_session(rec, include_token=False)

    def get_metrics(
        self, *, sandbox_id: str, tenant_id: str, user_id: str
    ) -> dict[str, Any]:
        rec = self._require_owned_record(
            sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
        )
        if rec.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")
        getter = getattr(self.runtime, "get_metrics", None)
        if callable(getter):
            return getter(
                container_name=rec.container_name,
                machine_id=rec.fly_machine_id,
                vm_secret=rec.vm_secret,
                private_ip=rec.private_ip,
            )
        return {
            "sandbox_id": rec.sandbox_id,
            "template_id": rec.template_id,
            "backend": rec.backend,
            "real_daemons": False,
            "daemons": {},
            "ttl_remaining_seconds": max(0, int(rec.expires_epoch - self._now())),
            "fault_armed": rec.blind_fault_armed,
        }

    def inject_blind_fault(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        user_id: str,
        seed: int | None = None,
        scenario_id: str | None = None,
    ) -> ChaosInjectResponse:
        rec = self._require_owned_record(
            sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
        )
        if rec.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")
        fault: ChaosFault | None = None
        injector = getattr(self.runtime, "inject_fault", None)
        if callable(injector):
            real_fault = injector(
                container_name=rec.container_name,
                machine_id=rec.fly_machine_id,
                vm_secret=rec.vm_secret,
                private_ip=rec.private_ip,
                scenario_id=scenario_id,
                seed=seed,
            )
            if real_fault is not None:
                fault = ChaosFault(
                    id=real_fault.fault_id,
                    category=rec.module_id,
                    symptom=real_fault.symptom,
                    remediation_hint=real_fault.remediation_hint,
                )
        if fault is None:
            fault = select_blind_fault(seed=seed)
        now = self._now()
        rec.blind_fault_armed = True
        rec.blind_fault_id = fault.id
        rec.blind_symptom = fault.symptom
        rec.blind_remediation = fault.remediation_hint
        rec.fault_started_epoch = now
        self._store.upsert(rec)
        return ChaosInjectResponse(
            sandbox_id=sandbox_id,
            status="armed",
            symptom=fault.symptom,
            started_at=datetime.fromtimestamp(now, UTC).isoformat(),
        )

    def control_loadgen(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        user_id: str,
        enabled: bool,
        rps: int = 50,
        duration_s: int = 60,
    ) -> dict[str, Any]:
        rec = self._require_owned_record(sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id)
        if rec.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")
        fn = getattr(self.runtime, "control_loadgen", None)
        if not callable(fn):
            return {"ok": True, "loadgen": {"active": False, "target_rps": 0}}
        return fn(
            container_name=rec.container_name,
            enabled=enabled,
            rps=rps,
            duration_s=duration_s,
            machine_id=rec.fly_machine_id,
            vm_secret=rec.vm_secret,
            private_ip=rec.private_ip,
        )

    def run_project_action(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        user_id: str,
        action: str,
        project_id: str,
        use_reference: bool = False,
    ) -> dict[str, Any]:
        rec = self._require_owned_record(sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id)
        if rec.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")
        fn = getattr(self.runtime, "run_project_action", None)
        if not callable(fn):
            raise ValueError("Project runner not supported by current backend")
        return fn(
            container_name=rec.container_name,
            action=action,
            project_id=project_id,
            use_reference=use_reference,
            machine_id=rec.fly_machine_id,
            vm_secret=rec.vm_secret,
            private_ip=rec.private_ip,
        )

    def list_files(self, *, sandbox_id: str, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        rec = self._require_owned_record(sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id)
        if rec.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")
        fn = getattr(self.runtime, "list_files", None)
        if not callable(fn):
            return []
        return fn(
            container_name=rec.container_name,
            machine_id=rec.fly_machine_id,
            vm_secret=rec.vm_secret,
            private_ip=rec.private_ip,
        )

    def read_file(
        self, *, sandbox_id: str, tenant_id: str, user_id: str, path: str
    ) -> dict[str, Any]:
        rec = self._require_owned_record(sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id)
        if rec.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")
        fn = getattr(self.runtime, "read_file", None)
        if not callable(fn):
            raise FileNotFoundError("File editor not supported by current backend")
        return fn(
            container_name=rec.container_name,
            path=path,
            machine_id=rec.fly_machine_id,
            vm_secret=rec.vm_secret,
            private_ip=rec.private_ip,
        )

    def write_file(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        user_id: str,
        path: str,
        content: str,
        reload: bool = False,
    ) -> dict[str, Any]:
        rec = self._require_owned_record(sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id)
        if rec.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")
        fn = getattr(self.runtime, "write_file", None)
        if not callable(fn):
            raise ValueError("File editor not supported by current backend")
        return fn(
            container_name=rec.container_name,
            path=path,
            content=content,
            reload=reload,
            machine_id=rec.fly_machine_id,
            vm_secret=rec.vm_secret,
            private_ip=rec.private_ip,
        )

    def verify_and_issue_receipt(
        self, *, sandbox_id: str, tenant_id: str, user_id: str
    ) -> VerifySandboxResponse:
        rec = self._require_owned_record(
            sandbox_id=sandbox_id, tenant_id=tenant_id, user_id=user_id
        )
        if rec.status != "running":
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' is not running")

        probe_checks = getattr(self.runtime, "exec_health_probe_checks", None)
        granular_checks: list[dict[str, Any]] = []
        if callable(probe_checks):
            healthy, detail, granular_checks = probe_checks(
                container_name=rec.container_name,
                machine_id=rec.fly_machine_id,
                vm_secret=rec.vm_secret,
                private_ip=rec.private_ip,
            )
        else:
            healthy, detail = self.runtime.exec_health_probe(
                container_name=rec.container_name,
                machine_id=rec.fly_machine_id,
                vm_secret=rec.vm_secret,
                private_ip=rec.private_ip,
            )

        start_ts = rec.fault_started_epoch or rec.created_epoch
        elapsed = max(0.0, round(self._now() - start_ts, 2))
        revealed = rec.blind_fault_id if (healthy and rec.blind_fault_id) else None
        hint = rec.blind_remediation if (healthy and rec.blind_remediation) else None

        checks_payload: list[dict[str, Any]] = [
            {
                "name": "sandbox_sla_probe",
                "status": "pass" if healthy else "fail",
                "detail": detail,
            }
        ]
        for gc in granular_checks:
            checks_payload.append(
                {
                    "name": str(gc.get("id") or gc.get("label") or "check"),
                    "label": str(gc.get("label") or gc.get("id") or "Check"),
                    "status": "pass" if gc.get("passed") else "fail",
                    "detail": str(gc.get("detail") or ""),
                }
            )

        receipt: dict[str, Any] = {
            "schemaVersion": 1,
            "module": rec.module_id,
            "sandboxId": sandbox_id,
            "templateId": rec.template_id,
            "passed": healthy,
            "passedAt": datetime.now(UTC).isoformat(),
            "elapsedSeconds": elapsed,
            "checks": checks_payload,
            "verifiedSkillIds": [],
        }
        receipt["sha256"] = compute_receipt_sha256(receipt)

        if healthy:
            rec.blind_fault_armed = False
            rec.blind_fault_id = None
            rec.blind_symptom = None
            rec.blind_remediation = None
            rec.fault_started_epoch = None
            self._store.upsert(rec)

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
        if rec.status == "running":
            self.runtime.stop_sandbox(
                container_name=rec.container_name,
                network_name=rec.network_name,
                machine_id=rec.fly_machine_id,
            )
            rec.status = "terminated"
            rec.terminal_token = None
            self._store.upsert(rec)
        return _record_to_session(rec, include_token=False)

    def admin_force_terminate(self, *, sandbox_id: str) -> SandboxSession:
        rec = self._store.get(sandbox_id)
        if rec is None:
            raise SandboxNotFoundError(f"Sandbox '{sandbox_id}' not found")
        if rec.status == "running":
            self.runtime.stop_sandbox(
                container_name=rec.container_name,
                network_name=rec.network_name,
                machine_id=rec.fly_machine_id,
            )
            rec.status = "terminated"
            rec.terminal_token = None
            self._store.upsert(rec)
        return _record_to_session(rec, include_token=False)
