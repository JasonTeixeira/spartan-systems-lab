"""Durable stateless session store for multi-replica Cloud Sandbox Orchestrator.

Uses Supabase PostgREST (`public.orchestrator_sandbox_state`) in production so any
orchestrator replica can authenticate WebSockets, proxy chaos/verify, reap expired VMs,
or survive deploys without dropping active Firecracker sessions.

Falls back to `InMemorySessionStore` automatically in local development and unit tests.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class StoredSandboxRecord:
    sandbox_id: str
    tenant_id: str
    user_id: str
    template_id: str
    module_id: str
    tier: str
    backend: str
    status: str
    container_name: str
    network_name: str
    fly_machine_id: str | None
    private_ip: str | None
    region: str | None
    vm_secret: str | None
    terminal_token: str | None
    terminal_ws_url: str
    cpu_limit: float
    memory_mb: int
    pids_limit: int
    blind_fault_armed: bool
    blind_fault_id: str | None
    blind_symptom: str | None
    blind_remediation: str | None
    fault_started_epoch: float | None
    created_epoch: float
    expires_epoch: int
    security_profile: list[str]

    def to_row(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "template_id": self.template_id,
            "module_id": self.module_id,
            "tier": self.tier,
            "backend": self.backend,
            "status": self.status,
            "container_name": self.container_name,
            "network_name": self.network_name,
            "fly_machine_id": self.fly_machine_id,
            "private_ip": self.private_ip,
            "region": self.region,
            "vm_secret": self.vm_secret,
            "terminal_token": self.terminal_token,
            "terminal_ws_url": self.terminal_ws_url,
            "cpu_limit": self.cpu_limit,
            "memory_mb": self.memory_mb,
            "pids_limit": self.pids_limit,
            "blind_fault_armed": self.blind_fault_armed,
            "blind_fault_id": self.blind_fault_id,
            "blind_symptom": self.blind_symptom,
            "blind_remediation": self.blind_remediation,
            "fault_started_epoch": self.fault_started_epoch,
            "created_epoch": self.created_epoch,
            "expires_epoch": self.expires_epoch,
            "security_profile": self.security_profile,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> StoredSandboxRecord:
        sec = row.get("security_profile")
        if not isinstance(sec, list):
            sec = []
        return cls(
            sandbox_id=str(row["sandbox_id"]),
            tenant_id=str(row["tenant_id"]),
            user_id=str(row["user_id"]),
            template_id=str(row["template_id"]),
            module_id=str(row["module_id"]),
            tier=str(row["tier"]),
            backend=str(row.get("backend") or "memory"),
            status=str(row.get("status") or "running"),
            container_name=str(row["container_name"]),
            network_name=str(row["network_name"]),
            fly_machine_id=row.get("fly_machine_id"),
            private_ip=row.get("private_ip"),
            region=row.get("region"),
            vm_secret=row.get("vm_secret"),
            terminal_token=row.get("terminal_token"),
            terminal_ws_url=str(row["terminal_ws_url"]),
            cpu_limit=float(row.get("cpu_limit") or 1.0),
            memory_mb=int(row.get("memory_mb") or 512),
            pids_limit=int(row.get("pids_limit") or 128),
            blind_fault_armed=bool(row.get("blind_fault_armed", False)),
            blind_fault_id=row.get("blind_fault_id"),
            blind_symptom=row.get("blind_symptom"),
            blind_remediation=row.get("blind_remediation"),
            fault_started_epoch=(
                float(row["fault_started_epoch"])
                if row.get("fault_started_epoch") is not None
                else None
            ),
            created_epoch=float(row["created_epoch"]),
            expires_epoch=int(row["expires_epoch"]),
            security_profile=[str(x) for x in sec],
        )


class SessionStore(Protocol):
    store_name: str

    def upsert(self, record: StoredSandboxRecord) -> None: ...
    def get(self, sandbox_id: str) -> StoredSandboxRecord | None: ...
    def list_running(
        self, *, tenant_id: str | None = None, user_id: str | None = None
    ) -> list[StoredSandboxRecord]: ...


class InMemorySessionStore:
    store_name: str = "memory"

    def __init__(self) -> None:
        self._items: dict[str, StoredSandboxRecord] = {}

    def upsert(self, record: StoredSandboxRecord) -> None:
        self._items[record.sandbox_id] = record

    def get(self, sandbox_id: str) -> StoredSandboxRecord | None:
        return self._items.get(sandbox_id)

    def list_running(
        self, *, tenant_id: str | None = None, user_id: str | None = None
    ) -> list[StoredSandboxRecord]:
        out: list[StoredSandboxRecord] = []
        for rec in self._items.values():
            if rec.status != "running":
                continue
            if tenant_id is not None and rec.tenant_id != tenant_id:
                continue
            if user_id is not None and rec.user_id != user_id:
                continue
            out.append(rec)
        return out


class SupabaseSessionStore:
    """Zero-dependency PostgREST durable store for horizontal multi-replica orchestrators."""

    store_name: str = "supabase"

    def __init__(self, *, supabase_url: str, service_role_key: str) -> None:
        self._base = supabase_url.rstrip("/") + "/rest/v1/orchestrator_sandbox_state"
        self._key = service_role_key.strip()

    def _request(
        self,
        method: str,
        query: str = "",
        body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        url = f"{self._base}{query}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase store {method} {exc.code}: {detail[:240]}") from None

    def upsert(self, record: StoredSandboxRecord) -> None:
        self._request(
            "POST",
            query="?on_conflict=sandbox_id",
            body=record.to_row(),
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def get(self, sandbox_id: str) -> StoredSandboxRecord | None:
        qs = urllib.parse.urlencode({"sandbox_id": f"eq.{sandbox_id}", "select": "*", "limit": "1"})
        rows = self._request("GET", query=f"?{qs}")
        if isinstance(rows, list) and rows:
            return StoredSandboxRecord.from_row(rows[0])
        return None

    def list_running(
        self, *, tenant_id: str | None = None, user_id: str | None = None
    ) -> list[StoredSandboxRecord]:
        params: dict[str, str] = {"status": "eq.running", "select": "*", "order": "created_epoch.desc"}
        if tenant_id is not None:
            params["tenant_id"] = f"eq.{tenant_id}"
        if user_id is not None:
            params["user_id"] = f"eq.{user_id}"
        qs = urllib.parse.urlencode(params)
        rows = self._request("GET", query=f"?{qs}")
        if not isinstance(rows, list):
            return []
        return [StoredSandboxRecord.from_row(r) for r in rows]
