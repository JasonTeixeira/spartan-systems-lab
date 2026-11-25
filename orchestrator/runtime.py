"""Hardened multi-backend sandbox runtime (Fly Firecracker KVM, Docker, Linux PTY, Memory)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from orchestrator.grader import (
    RealLabFault,
    arm_scenario_fault,
    list_editable_files,
    probe_live_telemetry,
    provision_workspace,
    read_workspace_file,
    reload_lab_daemon,
    scaffold_workspace_project,
    test_workspace_project,
    verify_workspace_checks,
    verify_workspace_sla,
    write_workspace_file,
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
        "-e",
        f"SPARTAN_SANDBOX_ID={sandbox_id}",
        "-e",
        f"SPARTAN_MODULE={template.module}",
    ]
    if template.needs_net_admin:
        cmd.extend(["--cap-add=NET_ADMIN"])
    cmd.extend([template.image, "sleep", str(quota.ttl_minutes * 60)])
    return cmd


def security_profile_summary(
    template: LabTemplateSpec, quota: TierQuota, *, backend: str = "fly"
) -> list[str]:
    if backend == "fly":
        return [
            "kvm-firecracker-microvm",
            "zero-public-ip-6pn-mesh",
            "per-vm-ephemeral-secret",
            "unprivileged-operator-uid1000",
            "immutable-root-grader-0700",
            f"cpus={max(1, int(round(quota.cpu_limit)))}",
            f"memory={max(512, quota.memory_mb)}m",
            "auto-destroy-ttl-and-idle",
        ]
    flags = [
        "non-root-shell",
        "no-new-privileges",
        "immutable-grader",
        f"cpus={quota.cpu_limit}",
        f"memory={quota.memory_mb}m",
        f"pids-limit={quota.pids_limit}",
    ]
    if template.needs_net_admin:
        flags.append("cap-add=NET_ADMIN")
    return flags


@dataclass(frozen=True)
class StartSandboxResult:
    machine_id: str | None = None
    region: str | None = None
    private_ip: str | None = None


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
        vm_secret: str = "",
        arm_blind_chaos: bool = False,
    ) -> StartSandboxResult | None: ...

    def stop_sandbox(
        self, *, container_name: str, network_name: str, machine_id: str | None = None
    ) -> None: ...

    def exec_health_probe(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> tuple[bool, str]: ...


@dataclass
class MemorySandboxRuntime:
    """Deterministic in-memory runtime for fast unit/CI tests without Docker daemon."""

    backend_name: str = "memory"
    running_containers: dict[str, list[str]] = field(default_factory=dict)
    created_networks: set[str] = field(default_factory=set)

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
        vm_secret: str = "",
        arm_blind_chaos: bool = False,
    ) -> StartSandboxResult:
        _ = (vm_secret, arm_blind_chaos)
        cmd = build_hardened_docker_run_cmd(
            sandbox_id=sandbox_id,
            tenant_id=tenant_id,
            container_name=container_name,
            network_name=network_name,
            template=template,
            quota=quota,
            expires_epoch=expires_epoch,
        )
        self.created_networks.add(network_name)
        self.running_containers[container_name] = cmd
        return StartSandboxResult()

    def stop_sandbox(
        self, *, container_name: str, network_name: str, machine_id: str | None = None
    ) -> None:
        _ = machine_id
        self.running_containers.pop(container_name, None)
        self.created_networks.discard(network_name)

    def exec_health_probe(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> tuple[bool, str]:
        _ = (machine_id, vm_secret, private_ip)
        alive = container_name in self.running_containers
        return alive, "container running" if alive else "container missing"


@dataclass
class DockerSandboxRuntime:
    """Production Docker CLI runtime with per-sandbox isolated bridge networks."""

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
        vm_secret: str = "",
        arm_blind_chaos: bool = False,
    ) -> StartSandboxResult:
        _ = (vm_secret, arm_blind_chaos)
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
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return StartSandboxResult()

    def stop_sandbox(
        self, *, container_name: str, network_name: str, machine_id: str | None = None
    ) -> None:
        _ = machine_id
        subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True, text=True)
        subprocess.run(["docker", "network", "rm", network_name], check=False, capture_output=True, text=True)

    def exec_health_probe(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> tuple[bool, str]:
        _ = (machine_id, vm_secret, private_ip)
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
    image_override: str | None = None,
    vm_secret: str = "",
    arm_blind_chaos: bool = False,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Build a hardened Fly Machines KVM Firecracker MicroVM launch payload (zero public IP)."""
    cpus = max(1, int(round(quota.cpu_limit)))
    mem_mb = max(512, int(quota.memory_mb))
    env: dict[str, str] = {
        "SPARTAN_SANDBOX_ID": sandbox_id,
        "SPARTAN_TENANT_ID": tenant_id,
        "SPARTAN_TEMPLATE": template.id,
        "SPARTAN_MODULE": template.module,
        "SPARTAN_EXPIRES_AT": str(expires_epoch),
        "SPARTAN_ARM_CHAOS": "1" if arm_blind_chaos else "0",
        "SPARTAN_IDLE_TIMEOUT_SECONDS": "1200",
    }
    if scenario_id:
        env["SPARTAN_SCENARIO_ID"] = scenario_id
    if vm_secret:
        env["VM_SESSION_SECRET"] = vm_secret
    return {
        "name": container_name,
        "region": region,
        "config": {
            "image": (image_override or template.image).strip(),
            "auto_destroy": True,
            "restart": {"policy": "no"},
            "guest": {
                "cpu_kind": "shared",
                "cpus": cpus,
                "memory_mb": mem_mb,
            },
            "env": env,
            "metadata": {
                "spartan_managed": "true",
                "spartan_sandbox": sandbox_id,
                "spartan_tenant": tenant_id,
                "spartan_template": template.id,
            },
        },
    }


FlyHttpSender = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]
VmHttpSender = Callable[[str, str, dict[str, str], dict[str, Any] | None], tuple[int, dict[str, Any]]]


@dataclass
class FlyMachinesRuntime:
    """Production hardware-isolated KVM Firecracker MicroVM runtime via Fly Machines API + 6pn mesh."""

    app_name: str
    api_token: str
    region: str = "iad"
    api_base: str = "https://api.machines.dev/v1"
    image_override: str = ""
    vm_agent_port: int = 8091
    backend_name: str = "fly"
    http_sender: FlyHttpSender | None = None
    vm_http_sender: VmHttpSender | None = None
    warm_pool_size: int = 0
    _machine_ids: dict[str, str] = field(default_factory=dict)
    _warm_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _resolved_image(self, template_image: str = "") -> str:
        return (
            self.image_override
            or os.environ.get("FLY_SANDBOX_IMAGE", "").strip()
            or template_image
            or "registry.fly.io/crucible-sandboxes:v5"
        )

    def _list_warm_machines(self, resolved_image: str) -> list[dict[str, Any]]:
        if not self.api_token and self.http_sender is None:
            return []
        try:
            status, resp = self._request("GET", f"/apps/{self.app_name}/machines", timeout=10.0)
        except RuntimeError:
            return []
        if status != 200 or not isinstance(resp, list):
            return []
        warm: list[dict[str, Any]] = []
        for m in resp:
            if not isinstance(m, dict):
                continue
            cfg = m.get("config") or {}
            meta = cfg.get("metadata") or {}
            if (
                meta.get("crucible_pool") == "warm"
                and (
                    meta.get("crucible_image") == resolved_image
                    or str(cfg.get("image", "")).strip().startswith(resolved_image)
                )
                and str(m.get("region", self.region)) == self.region
                and str(m.get("state", "")) in {"stopped", "created"}
            ):
                warm.append(m)
        return warm

    def ensure_warm_pool(self, target_size: int | None = None) -> dict[str, Any]:
        """Ensure `target_size` brand-new stopped (`skip_launch: true`) Firecracker VMs exist ($0/hr idle)."""
        desired = self.warm_pool_size if target_size is None else max(0, min(5, int(target_size)))
        resolved_image = self._resolved_image()
        if desired <= 0:
            return {"desired": 0, "ready": 0, "created": 0}
        with self._warm_lock:
            existing = self._list_warm_machines(resolved_image)
            needed = max(0, desired - len(existing))
            created = 0
            for idx in range(needed):
                warm_name = f"crucible-warm-{int(time.time())}-{idx}"
                payload = {
                    "name": warm_name,
                    "region": self.region,
                    "skip_launch": True,
                    "config": {
                        "image": resolved_image,
                        "auto_destroy": False,
                        "restart": {"policy": "no"},
                        "guest": {"cpu_kind": "shared", "cpus": 1, "memory_mb": 1024},
                        "env": {
                            "SPARTAN_SANDBOX_ID": "sbx_warm_standby",
                            "SPARTAN_TEMPLATE": "lab1-core-engine",
                            "SPARTAN_MODULE": "M01",
                            "SPARTAN_IDLE_TIMEOUT_SECONDS": "1200",
                        },
                        "metadata": {
                            "crucible_pool": "warm",
                            "crucible_image": resolved_image,
                            "spartan_managed": "true",
                        },
                    },
                }
                try:
                    st, resp = self._request("POST", f"/apps/{self.app_name}/machines", payload, timeout=40.0)
                    if st < 400 and isinstance(resp, dict) and resp.get("id"):
                        created += 1
                except RuntimeError:
                    break
            return {"desired": desired, "ready": len(existing) + created, "created": created, "image": resolved_image}

    def _replenish_warm_pool_async(self) -> None:
        if self.warm_pool_size <= 0 or (self.http_sender is not None and self.vm_http_sender is None):
            return
        t = threading.Thread(target=self.ensure_warm_pool, daemon=True)
        t.start()

    def _try_claim_warm_machine(
        self,
        *,
        resolved_image: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Atomically lease & claim a stopped Firecracker VM, inject fresh secrets/config & start it."""
        if self.warm_pool_size <= 0:
            return None
        candidates = self._list_warm_machines(resolved_image)
        if not candidates:
            return None
        for m in candidates:
            mid = str(m.get("id", ""))
            if not mid:
                continue
            cfg = dict(payload["config"])
            cfg["auto_destroy"] = False
            meta = dict(cfg.get("metadata") or {})
            meta["crucible_pool"] = "claimed"
            cfg["metadata"] = meta
            lease_nonce: str | None = None
            try:
                # 1. Acquire Fly Machine Lease (required by Fly Machines API to update a stopped machine)
                st_lease, lease_resp = self._request(
                    "POST",
                    f"/apps/{self.app_name}/machines/{mid}/lease",
                    {"ttl": 30},
                    timeout=10.0,
                )
                if st_lease < 400 and isinstance(lease_resp, dict):
                    data_obj = lease_resp.get("data") if isinstance(lease_resp.get("data"), dict) else lease_resp
                    raw_nonce = data_obj.get("nonce") if isinstance(data_obj, dict) else None
                    if isinstance(raw_nonce, str) and raw_nonce:
                        lease_nonce = raw_nonce
                extra_headers = {"fly-machine-lease-nonce": lease_nonce} if lease_nonce else None

                # 2. Update stopped warm machine config with brand-new per-user env & fresh VM_SESSION_SECRET.
                # Pass skip_launch=True, wait for the config replacement to reach `stopped` (eliminating HTTP 412),
                # then issue `/start` so Fly boots the pre-pulled Firecracker MicroVM cleanly in-place!
                st, upd = self._request(
                    "POST",
                    f"/apps/{self.app_name}/machines/{mid}",
                    {"config": cfg, "skip_launch": True},
                    timeout=25.0,
                    extra_headers=extra_headers,
                )
                if st >= 400 or not isinstance(upd, dict):
                    continue
                new_inst = upd.get("instance_id") or m.get("instance_id")
                if self.http_sender is None and new_inst:
                    try:
                        self._request(
                            "GET",
                            f"/apps/{self.app_name}/machines/{mid}/wait?state=stopped&instance_id={new_inst}&timeout=15",
                            None,
                            timeout=18.0,
                        )
                    except RuntimeError:
                        pass
                st_start, _ = self._request(
                    "POST",
                    f"/apps/{self.app_name}/machines/{mid}/start",
                    None,
                    timeout=20.0,
                    extra_headers=extra_headers,
                )
                if st_start >= 400:
                    continue
                return {
                    "id": mid,
                    "region": str(upd.get("region") or m.get("region") or self.region),
                    "private_ip": upd.get("private_ip") or m.get("private_ip"),
                    "instance_id": new_inst,
                    "warm_claimed": True,
                }
            except RuntimeError:
                continue
            finally:
                if lease_nonce:
                    try:
                        self._request(
                            "DELETE",
                            f"/apps/{self.app_name}/machines/{mid}/lease",
                            None,
                            timeout=5.0,
                            extra_headers={"fly-machine-lease-nonce": lease_nonce},
                        )
                    except RuntimeError:
                        pass
        return None

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        timeout: float = 35.0,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self.api_base.rstrip('/')}{path}"
        if self.http_sender is not None:
            return self.http_sender(method, url, body)
        if not self.app_name or not self.api_token:
            raise RuntimeError("FLY_SANDBOX_APP_NAME and FLY_API_TOKEN are required for fly")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "User-Agent": "crucible-sandbox-orchestrator/2.0",
        }
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8") or "{}"
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Fly Machines API {exc.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Fly Machines API transport timeout: {exc}") from None

    def _vm_host(self, machine_id: str, private_ip: str | None = None) -> str:
        if private_ip and ":" in private_ip:
            return f"[{private_ip}]"
        if private_ip:
            return private_ip
        return f"{machine_id}.vm.{self.app_name}.internal"

    def _vm_base_url(self, machine_id: str, private_ip: str | None = None) -> str:
        return f"http://{self._vm_host(machine_id, private_ip)}:{self.vm_agent_port}"

    def get_internal_ws_url(self, *, machine_id: str, private_ip: str | None = None) -> str:
        return f"ws://{self._vm_host(machine_id, private_ip)}:{self.vm_agent_port}/internal/terminal"

    def _vm_request(
        self,
        *,
        machine_id: str,
        method: str,
        path: str,
        vm_secret: str | None = None,
        private_ip: str | None = None,
        body: dict[str, Any] | None = None,
        timeout: float = 12.0,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._vm_base_url(machine_id, private_ip)}{path}"
        headers = {"Content-Type": "application/json"}
        if vm_secret:
            headers["X-VM-Session-Secret"] = vm_secret
        if self.vm_http_sender is not None:
            return self.vm_http_sender(method, url, headers, body)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8") or "{}"
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return exc.code, {"error": detail}
        except Exception as exc:
            return 503, {"error": str(exc)}

    def _wait_until_vm_ready(
        self, *, machine_id: str, private_ip: str | None = None, instance_id: str | None = None, timeout_s: float = 35.0
    ) -> None:
        # In pure mocked Fly API unit tests (http_sender set without vm_http_sender), skip 6pn polling
        if self.http_sender is not None and self.vm_http_sender is None:
            return
        # Wait for Fly Machine to reach `started` state cleanly first (avoids premature DNS/TCP timeouts)
        if self.http_sender is None:
            wait_qs = f"state=started&timeout=25" + (f"&instance_id={instance_id}" if instance_id else "")
            try:
                self._request("GET", f"/apps/{self.app_name}/machines/{machine_id}/wait?{wait_qs}", timeout=30.0)
            except RuntimeError:
                pass
        deadline = time.time() + timeout_s
        last_err = "booting"
        while time.time() < deadline:
            status, payload = self._vm_request(
                machine_id=machine_id,
                private_ip=private_ip,
                method="GET",
                path="/internal/health",
                timeout=1.5,
            )
            if status == 200 and payload.get("ready") is True:
                return
            last_err = str(payload.get("error") or payload.get("status") or status)
            time.sleep(0.2)
        raise RuntimeError(f"Firecracker MicroVM {machine_id} did not become ready in {timeout_s}s ({last_err})")

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
        vm_secret: str = "",
        arm_blind_chaos: bool = False,
        scenario_id: str | None = None,
    ) -> StartSandboxResult:
        _ = network_name  # Fly provides hardware KVM + private 6pn WireGuard per MicroVM
        resolved_image = (
            self.image_override
            or os.environ.get("FLY_SANDBOX_IMAGE", "").strip()
            or template.image
        )
        payload = build_fly_machine_payload(
            sandbox_id=sandbox_id,
            tenant_id=tenant_id,
            container_name=container_name,
            template=template,
            quota=quota,
            expires_epoch=expires_epoch,
            region=self.region,
            image_override=resolved_image,
            vm_secret=vm_secret,
            arm_blind_chaos=arm_blind_chaos,
            scenario_id=scenario_id,
        )
        resp: dict[str, Any] | None = self._try_claim_warm_machine(
            resolved_image=resolved_image,
            payload=payload,
        )
        if resp is None:
            status, cold_resp = self._request("POST", f"/apps/{self.app_name}/machines", payload)
            if status >= 400 or not isinstance(cold_resp.get("id"), str):
                raise RuntimeError(f"Failed to boot Fly Firecracker Machine ({status}): {cold_resp}")
            resp = cold_resp
        self._replenish_warm_pool_async()
        machine_id = str(resp["id"])
        actual_region = str(resp.get("region") or self.region)
        private_ip = str(resp["private_ip"]) if isinstance(resp.get("private_ip"), str) and resp.get("private_ip") else None
        instance_id = str(resp["instance_id"]) if isinstance(resp.get("instance_id"), str) else None
        self._machine_ids[container_name] = machine_id
        try:
            self._wait_until_vm_ready(
                machine_id=machine_id,
                private_ip=private_ip,
                instance_id=instance_id,
            )
        except Exception:
            # Clean up failed VM immediately so it never leaks billing
            self.stop_sandbox(container_name=container_name, network_name=network_name, machine_id=machine_id)
            raise
        return StartSandboxResult(machine_id=machine_id, region=actual_region, private_ip=private_ip)

    def inject_fault(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
        scenario_id: str | None = None,
        seed: int | None = None,
    ) -> RealLabFault | None:
        mid = machine_id or self._machine_ids.get(container_name)
        if not mid or (self.http_sender is not None and self.vm_http_sender is None):
            return None
        body: dict[str, Any] = {}
        if scenario_id:
            body["scenario_id"] = scenario_id
        if seed is not None:
            body["seed"] = seed
        status, resp = self._vm_request(
            machine_id=mid,
            private_ip=private_ip,
            method="POST",
            path="/internal/chaos",
            vm_secret=vm_secret,
            body=body,
            timeout=15.0,
        )
        if status != 200 or not isinstance(resp.get("fault_id"), str):
            raise RuntimeError(f"Failed to inject chaos in Firecracker VM {mid}: {resp}")
        return RealLabFault(
            fault_id=str(resp["fault_id"]),
            symptom=str(resp.get("symptom", "")),
            remediation_hint=str(resp.get("remediation_hint", "")),
        )

    def control_loadgen(
        self,
        *,
        container_name: str,
        enabled: bool,
        rps: int = 50,
        duration_s: int = 60,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        mid = machine_id or self._machine_ids.get(container_name)
        if not mid:
            raise RuntimeError("VM not tracked")
        status, resp = self._vm_request(
            machine_id=mid,
            private_ip=private_ip,
            method="POST",
            path="/internal/loadgen",
            vm_secret=vm_secret,
            body={"enabled": enabled, "rps": rps, "duration_s": duration_s},
            timeout=10.0,
        )
        if status != 200:
            raise RuntimeError(f"Loadgen control failed ({status}): {resp}")
        return resp

    def run_project_action(
        self,
        *,
        container_name: str,
        action: str,
        project_id: str,
        use_reference: bool = False,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        mid = machine_id or self._machine_ids.get(container_name)
        if not mid:
            raise RuntimeError("VM not tracked")
        path = "/internal/project/scaffold" if action == "scaffold" else "/internal/project/test"
        status, resp = self._vm_request(
            machine_id=mid,
            private_ip=private_ip,
            method="POST",
            path=path,
            vm_secret=vm_secret,
            body={"project_id": project_id, "use_reference": use_reference},
            timeout=20.0,
        )
        if status >= 400:
            raise ValueError(str(resp.get("detail") or resp.get("error") or f"Project action failed ({status})"))
        return resp

    def get_metrics(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        mid = machine_id or self._machine_ids.get(container_name)
        if not mid:
            return {"status": "unknown"}
        status, resp = self._vm_request(
            machine_id=mid,
            private_ip=private_ip,
            method="GET",
            path="/internal/metrics",
            vm_secret=vm_secret,
            timeout=5.0,
        )
        return resp if status == 200 else {"status": "unreachable", "error": resp.get("error")}

    def list_files(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> list[dict[str, Any]]:
        mid = machine_id or self._machine_ids.get(container_name)
        if not mid:
            return []
        status, resp = self._vm_request(
            machine_id=mid, private_ip=private_ip, method="GET", path="/internal/files", vm_secret=vm_secret, timeout=8.0
        )
        return list(resp.get("files", [])) if status == 200 else []

    def read_file(
        self,
        *,
        container_name: str,
        path: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        import urllib.parse

        mid = machine_id or self._machine_ids.get(container_name)
        if not mid:
            raise FileNotFoundError("VM not tracked")
        qs = urllib.parse.urlencode({"path": path})
        status, resp = self._vm_request(
            machine_id=mid,
            private_ip=private_ip,
            method="GET",
            path=f"/internal/files/read?{qs}",
            vm_secret=vm_secret,
            timeout=8.0,
        )
        if status == 404:
            raise FileNotFoundError(str(resp.get("detail") or resp.get("error") or "File not found"))
        if status >= 400:
            raise ValueError(str(resp.get("detail") or resp.get("error") or f"Read failed ({status})"))
        return resp

    def write_file(
        self,
        *,
        container_name: str,
        path: str,
        content: str,
        reload: bool = False,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        mid = machine_id or self._machine_ids.get(container_name)
        if not mid:
            raise ValueError("VM not tracked")
        status, resp = self._vm_request(
            machine_id=mid,
            private_ip=private_ip,
            method="PUT",
            path="/internal/files/write",
            vm_secret=vm_secret,
            body={"path": path, "content": content, "reload": reload},
            timeout=15.0,
        )
        if status >= 400:
            raise ValueError(str(resp.get("detail") or resp.get("error") or f"Write failed ({status})"))
        return resp

    def exec_health_probe_checks(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> tuple[bool, str, list[dict[str, Any]]]:
        mid = machine_id or self._machine_ids.get(container_name)
        if not mid:
            return False, "fly machine not tracked", []
        if self.http_sender is not None and self.vm_http_sender is None:
            ok, detail = self.exec_health_probe(container_name=container_name, machine_id=mid)
            return ok, detail, []
        status, resp = self._vm_request(
            machine_id=mid,
            private_ip=private_ip,
            method="POST",
            path="/internal/verify",
            vm_secret=vm_secret,
            body={},
            timeout=20.0,
        )
        if status != 200:
            return False, f"Firecracker grader unreachable ({status}): {resp.get('error', 'unknown')}", []
        checks = resp.get("checks")
        return bool(resp.get("passed", False)), str(resp.get("detail", "verified")), checks if isinstance(checks, list) else []

    def stop_sandbox(
        self, *, container_name: str, network_name: str, machine_id: str | None = None
    ) -> None:
        _ = network_name
        mid = machine_id or self._machine_ids.pop(container_name, None)
        self._machine_ids.pop(container_name, None)
        if not mid:
            return
        try:
            self._request("DELETE", f"/apps/{self.app_name}/machines/{mid}?force=true")
        except RuntimeError:
            # Already destroyed/stopped by auto_destroy
            pass

    def exec_health_probe(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> tuple[bool, str]:
        mid = machine_id or self._machine_ids.get(container_name)
        if not mid:
            return False, "fly machine not tracked"
        # In pure mocked Fly API unit tests (no vm_http_sender), fall back to Fly state check
        if self.http_sender is not None and self.vm_http_sender is None:
            status, resp = self._request("GET", f"/apps/{self.app_name}/machines/{mid}")
            state = str(resp.get("state", "unknown"))
            ok = status == 200 and state == "started"
            return ok, f"fly firecracker machine {mid} state={state}"
        status, resp = self._vm_request(
            machine_id=mid,
            private_ip=private_ip,
            method="POST",
            path="/internal/verify",
            vm_secret=vm_secret,
            body={},
            timeout=20.0,
        )
        if status != 200:
            return False, f"Firecracker grader unreachable ({status}): {resp.get('error', 'unknown')}"
        return bool(resp.get("passed", False)), str(resp.get("detail", "verified"))


@dataclass
class LinuxPtySandboxRuntime:
    """Local dev/CI Linux PTY runtime with tamper-proof grader (never used for multi-tenant prod)."""

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
        vm_secret: str = "",
        arm_blind_chaos: bool = False,
        scenario_id: str | None = None,
    ) -> StartSandboxResult:
        _ = (tenant_id, network_name, quota, expires_epoch, vm_secret)
        ws_dir = self.base_dir / sandbox_id
        if ws_dir.exists():
            shutil.rmtree(ws_dir, ignore_errors=True)
        if arm_blind_chaos:
            arm_scenario_fault(ws_dir, template.id, sandbox_id, scenario_id=scenario_id)
        else:
            provision_workspace(ws_dir, template.id, sandbox_id, arm_fault=False)
        self._workspaces[container_name] = (ws_dir, template.id, sandbox_id)
        return StartSandboxResult()

    def inject_fault(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
        scenario_id: str | None = None,
        seed: int | None = None,
    ) -> RealLabFault | None:
        _ = (machine_id, vm_secret, private_ip)
        entry = self._workspaces.get(container_name)
        if not entry:
            return None
        ws_dir, template_id, sandbox_id = entry
        return arm_scenario_fault(ws_dir, template_id, sandbox_id, scenario_id=scenario_id, seed=seed)

    def control_loadgen(
        self,
        *,
        container_name: str,
        enabled: bool,
        rps: int = 50,
        duration_s: int = 60,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        _ = (container_name, duration_s, machine_id, vm_secret, private_ip)
        return {
            "ok": True,
            "loadgen": {
                "active": bool(enabled),
                "target_rps": rps if enabled else 0,
                "actual_rps": float(rps) if enabled else 0.0,
                "total_requests": 0,
                "error_count": 0,
                "error_rate_pct": 0.0,
                "p50_ms": 4.2,
                "p95_ms": 9.8,
                "p99_ms": 14.5,
                "remaining_s": duration_s if enabled else 0,
            },
        }

    def run_project_action(
        self,
        *,
        container_name: str,
        action: str,
        project_id: str,
        use_reference: bool = False,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        _ = (machine_id, vm_secret, private_ip)
        entry = self._workspaces.get(container_name)
        if not entry:
            raise ValueError("sandbox workspace not found")
        ws_dir = entry[0]
        if action == "scaffold":
            return scaffold_workspace_project(ws_dir, project_id, use_reference=use_reference)
        return test_workspace_project(ws_dir, project_id)

    def get_workspace_dir(self, *, container_name: str) -> Path | None:
        entry = self._workspaces.get(container_name)
        return entry[0] if entry else None

    def stop_sandbox(
        self, *, container_name: str, network_name: str, machine_id: str | None = None
    ) -> None:
        _ = (network_name, machine_id)
        entry = self._workspaces.pop(container_name, None)
        if entry and entry[0].exists():
            shutil.rmtree(entry[0], ignore_errors=True)

    def exec_health_probe(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> tuple[bool, str]:
        _ = (machine_id, vm_secret, private_ip)
        entry = self._workspaces.get(container_name)
        if not entry:
            return False, "sandbox workspace not found"
        ws_dir, template_id, _ = entry
        return verify_workspace_sla(ws_dir, template_id)

    def exec_health_probe_checks(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> tuple[bool, str, list[dict[str, Any]]]:
        _ = (machine_id, vm_secret, private_ip)
        entry = self._workspaces.get(container_name)
        if not entry:
            return False, "sandbox workspace not found", []
        ws_dir, template_id, _ = entry
        return verify_workspace_checks(ws_dir, template_id)

    def get_metrics(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        _ = (machine_id, vm_secret, private_ip)
        entry = self._workspaces.get(container_name)
        if not entry:
            return {"status": "missing"}
        ws_dir, template_id, sid = entry
        return {
            "sandbox_id": sid,
            "template_id": template_id,
            "backend": "linux-pty",
            "real_daemons": False,
            "daemons": {},
            "telemetry": probe_live_telemetry(ws_dir, template_id),
        }

    def list_files(
        self,
        *,
        container_name: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> list[dict[str, Any]]:
        _ = (machine_id, vm_secret, private_ip)
        entry = self._workspaces.get(container_name)
        return list_editable_files(entry[0]) if entry else []

    def read_file(
        self,
        *,
        container_name: str,
        path: str,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        _ = (machine_id, vm_secret, private_ip)
        entry = self._workspaces.get(container_name)
        if not entry:
            raise FileNotFoundError("sandbox workspace not found")
        return read_workspace_file(entry[0], path)

    def write_file(
        self,
        *,
        container_name: str,
        path: str,
        content: str,
        reload: bool = False,
        machine_id: str | None = None,
        vm_secret: str | None = None,
        private_ip: str | None = None,
    ) -> dict[str, Any]:
        _ = (machine_id, vm_secret, private_ip)
        entry = self._workspaces.get(container_name)
        if not entry:
            raise ValueError("sandbox workspace not found")
        ws_dir, template_id, _ = entry
        res = write_workspace_file(ws_dir, path, content)
        reload_res = reload_lab_daemon(ws_dir, template_id) if reload else None
        return {**res, "reload": reload_res, "telemetry": probe_live_telemetry(ws_dir, template_id)}
