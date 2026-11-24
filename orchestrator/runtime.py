"""Hardened container runtime abstraction (Docker CLI + deterministic memory backend)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from orchestrator.lab_scenarios import (
    RealLabFault,
    arm_scenario_fault,
    provision_workspace,
    verify_workspace_sla,
)
from orchestrator.models import LabTemplateSpec, TierQuota


def create_terminal_token(
    *,
    secret: str,
    sandbox_id: str,
    tenant_id: str,
    user_id: str,
    expires_epoch: int,
) -> str:
    """Create a short-lived HMAC-SHA256 signed token binding sandbox + tenant + user."""
    payload = {
        "sid": sandbox_id,
        "tid": tenant_id,
        "uid": user_id,
        "exp": expires_epoch,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_terminal_token(
    *,
    secret: str,
    token: str,
    expected_sandbox_id: str,
    now_epoch: int | None = None,
) -> dict[str, object] | None:
    """Verify HMAC-SHA256 signature, sandbox binding, and expiration."""
    if "." not in token:
        return None
    body, sig = token.split(".", 1)
    expected_sig = hmac.new(
        secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    pad = "=" * (-len(body) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    if decoded.get("sid") != expected_sandbox_id:
        return None
    now = int(time.time()) if now_epoch is None else now_epoch
    exp = decoded.get("exp")
    if not isinstance(exp, int) or exp <= now:
        return None
    return decoded


def build_hardened_docker_run_cmd(
    *,
    sandbox_id: str,
    tenant_id: str,
    container_name: str,
    network_name: str,
    template: LabTemplateSpec,
    quota: TierQuota,
    expires_epoch: int,
) -> list[str]:
    """Build a CIS/OWASP-hardened ephemeral Docker run command with strict isolation."""
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "--hostname",
        f"spartan-{template.id}",
        "--network",
        network_name,
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m",
        "--tmpfs",
        "/var/tmp:rw,noexec,nosuid,size=64m",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--cpus",
        str(quota.cpu_limit),
        "--memory",
        f"{quota.memory_mb}m",
        "--memory-swap",
        f"{quota.memory_mb}m",
        "--pids-limit",
        str(quota.pids_limit),
        "--label",
        "spartan.managed=true",
        "--label",
        f"spartan.sandbox={sandbox_id}",
        "--label",
        f"spartan.tenant={tenant_id}",
        "--label",
        f"spartan.expires_at={expires_epoch}",
    ]
    if template.needs_net_admin:
        cmd.extend(["--cap-add=NET_ADMIN"])
    cmd.extend([template.image, "sleep", "infinity"])
    return cmd


def security_profile_summary(template: LabTemplateSpec, quota: TierQuota) -> list[str]:
    caps = "cap-drop=ALL + NET_ADMIN (isolated net)" if template.needs_net_admin else "cap-drop=ALL"
    return [
        "read-only-rootfs",
        "no-new-privileges",
        caps,
        "isolated-internal-network",
        f"cpu={quota.cpu_limit}",
        f"mem={quota.memory_mb}MiB",
        f"pids={quota.pids_limit}",
    ]


class SandboxRuntime(Protocol):
    backend_name: str

    def start_sandbox(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        container_name: str,
        network_name: str,
        template: LabTemplateSpec,
        quota: TierQuota,
        expires_epoch: int,
    ) -> None: ...

    def stop_sandbox(self, *, container_name: str, network_name: str) -> None: ...

    def exec_health_probe(self, *, container_name: str) -> tuple[bool, str]: ...


@dataclass
class MemorySandboxRuntime:
    """In-memory deterministic runtime for CI, unit tests, and dry-run previews."""

    backend_name: str = "memory"

    def __post_init__(self) -> None:
        self.running_containers: dict[str, list[str]] = {}
        self.networks: set[str] = set()

    def start_sandbox(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        container_name: str,
        network_name: str,
        template: LabTemplateSpec,
        quota: TierQuota,
        expires_epoch: int,
    ) -> None:
        cmd = build_hardened_docker_run_cmd(
            sandbox_id=sandbox_id,
            tenant_id=tenant_id,
            container_name=container_name,
            network_name=network_name,
            template=template,
            quota=quota,
            expires_epoch=expires_epoch,
        )
        self.networks.add(network_name)
        self.running_containers[container_name] = cmd

    def stop_sandbox(self, *, container_name: str, network_name: str) -> None:
        self.running_containers.pop(container_name, None)
        self.networks.discard(network_name)

    def exec_health_probe(self, *, container_name: str) -> tuple[bool, str]:
        if container_name in self.running_containers:
            return True, "memory-probe healthy (p99=9.2ms, 0 blocked locks)"
        return False, "container not running"


@dataclass
class DockerSandboxRuntime:
    """Production Docker CLI runtime for dedicated Linux/Hetzner/Fly sandbox hosts."""

    backend_name: str = "docker"

    def start_sandbox(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        container_name: str,
        network_name: str,
        template: LabTemplateSpec,
        quota: TierQuota,
        expires_epoch: int,
    ) -> None:
        subprocess.run(
            ["docker", "network", "create", "--internal", network_name],
            check=True,
            capture_output=True,
            text=True,
        )
        cmd = build_hardened_docker_run_cmd(
            sandbox_id=sandbox_id,
            tenant_id=tenant_id,
            container_name=container_name,
            network_name=network_name,
            template=template,
            quota=quota,
            expires_epoch=expires_epoch,
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            subprocess.run(
                ["docker", "network", "rm", network_name],
                check=False,
                capture_output=True,
                text=True,
            )
            raise

    def stop_sandbox(self, *, container_name: str, network_name: str) -> None:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["docker", "network", "rm", network_name],
            check=False,
            capture_output=True,
            text=True,
        )

    def exec_health_probe(self, *, container_name: str) -> tuple[bool, str]:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        ok = proc.returncode == 0 and proc.stdout.strip() == "true"
        return ok, "container running" if ok else (proc.stderr.strip() or "container stopped")


def build_fly_machine_payload(
    *,
    sandbox_id: str,
    tenant_id: str,
    container_name: str,
    template: LabTemplateSpec,
    quota: TierQuota,
    expires_epoch: int,
    region: str = "iad",
) -> dict[str, Any]:
    """Build a hardened Fly Machines Firecracker MicroVM launch payload."""
    cpus = max(1, int(round(quota.cpu_limit)))
    return {
        "name": container_name,
        "region": region,
        "config": {
            "image": template.image,
            "auto_destroy": True,
            "restart": {"policy": "no"},
            "guest": {
                "cpu_kind": "shared",
                "cpus": cpus,
                "memory_mb": quota.memory_mb,
            },
            "env": {
                "SPARTAN_SANDBOX_ID": sandbox_id,
                "SPARTAN_TENANT_ID": tenant_id,
                "SPARTAN_MODULE": template.module,
                "SPARTAN_EXPIRES_AT": str(expires_epoch),
            },
            "metadata": {
                "spartan_managed": "true",
                "spartan_sandbox": sandbox_id,
                "spartan_tenant": tenant_id,
                "spartan_template": template.id,
            },
        },
    }


FlyHttpSender = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]


@dataclass
class FlyMachinesRuntime:
    """Production Firecracker MicroVM runtime backed by the Fly Machines REST API."""

    app_name: str
    api_token: str
    region: str = "iad"
    api_base: str = "https://api.machines.dev/v1"
    backend_name: str = "fly"
    http_sender: FlyHttpSender | None = None
    _machine_ids: dict[str, str] = field(default_factory=dict)

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self.api_base.rstrip('/')}{path}"
        if self.http_sender is not None:
            return self.http_sender(method, url, body)
        if not self.app_name or not self.api_token:
            raise RuntimeError("FLY_SANDBOX_APP_NAME and FLY_API_TOKEN are required for fly")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "User-Agent": "crucible-sandbox-orchestrator/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8") or "{}"
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Fly Machines API {exc.code}: {detail}") from None

    def start_sandbox(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        container_name: str,
        network_name: str,
        template: LabTemplateSpec,
        quota: TierQuota,
        expires_epoch: int,
    ) -> None:
        _ = network_name  # Fly provides hardware KVM + WireGuard isolation per MicroVM
        payload = build_fly_machine_payload(
            sandbox_id=sandbox_id,
            tenant_id=tenant_id,
            container_name=container_name,
            template=template,
            quota=quota,
            expires_epoch=expires_epoch,
            region=self.region,
        )
        status, resp = self._request("POST", f"/apps/{self.app_name}/machines", payload)
        if status >= 400 or not isinstance(resp.get("id"), str):
            raise RuntimeError(f"Failed to boot Fly Machine ({status}): {resp}")
        self._machine_ids[container_name] = str(resp["id"])

    def stop_sandbox(self, *, container_name: str, network_name: str) -> None:
        _ = network_name
        machine_id = self._machine_ids.pop(container_name, None)
        if not machine_id:
            return
        self._request("DELETE", f"/apps/{self.app_name}/machines/{machine_id}?force=true")

    def exec_health_probe(self, *, container_name: str) -> tuple[bool, str]:
        machine_id = self._machine_ids.get(container_name)
        if not machine_id:
            return False, "fly machine not tracked"
        status, resp = self._request("GET", f"/apps/{self.app_name}/machines/{machine_id}")
        state = str(resp.get("state", "unknown"))
        ok = status == 200 and state == "started"
        return ok, f"fly firecracker machine {machine_id} state={state}"


@dataclass
class LinuxPtySandboxRuntime:
    """Real Linux PTY runtime with isolated per-sandbox workspaces and live SLA probes."""

    base_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "spartan-sandboxes")
    backend_name: str = "linux-pty"
    _workspaces: dict[str, tuple[Path, str, str]] = field(default_factory=dict)

    def start_sandbox(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        container_name: str,
        network_name: str,
        template: LabTemplateSpec,
        quota: TierQuota,
        expires_epoch: int,
    ) -> None:
        _ = (tenant_id, network_name, quota, expires_epoch)
        ws_dir = self.base_dir / sandbox_id
        if ws_dir.exists():
            shutil.rmtree(ws_dir, ignore_errors=True)
        provision_workspace(ws_dir, template.id, sandbox_id, arm_fault=False)
        self._workspaces[container_name] = (ws_dir, template.id, sandbox_id)

    def inject_fault(self, *, container_name: str) -> RealLabFault | None:
        entry = self._workspaces.get(container_name)
        if not entry:
            return None
        ws_dir, template_id, sandbox_id = entry
        return arm_scenario_fault(ws_dir, template_id, sandbox_id)

    def get_workspace_dir(self, *, container_name: str) -> Path | None:
        entry = self._workspaces.get(container_name)
        return entry[0] if entry else None

    def stop_sandbox(self, *, container_name: str, network_name: str) -> None:
        _ = network_name
        entry = self._workspaces.pop(container_name, None)
        if entry and entry[0].exists():
            shutil.rmtree(entry[0], ignore_errors=True)

    def exec_health_probe(self, *, container_name: str) -> tuple[bool, str]:
        entry = self._workspaces.get(container_name)
        if not entry:
            return False, "sandbox workspace not found"
        ws_dir, template_id, _ = entry
        return verify_workspace_sla(ws_dir, template_id)
