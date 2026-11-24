"""Hardened container runtime abstraction (Docker CLI + deterministic memory backend)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

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
