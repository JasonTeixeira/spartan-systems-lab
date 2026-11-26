"""Security, quota, isolation & lifecycle tests for the Cloud Sandbox Orchestrator."""
from __future__ import annotations

from fastapi.testclient import TestClient

from orchestrator.app import create_orchestrator_app
from orchestrator.runtime import (
    FlyMachinesRuntime,
    MemorySandboxRuntime,
    verify_terminal_token,
)
from tools.war_room import verify_receipt_signature

TEST_API_KEY = "spartan-test-orchestrator-key-123456"
TEST_SIGNING_SECRET = "spartan-test-terminal-signing-secret-987654"


def _make_client() -> tuple[TestClient, MemorySandboxRuntime]:
    rt = MemorySandboxRuntime()
    app = create_orchestrator_app(
        api_key=TEST_API_KEY,
        signing_secret=TEST_SIGNING_SECRET,
        runtime=rt,
    )
    return TestClient(app), rt


def test_orchestrator_fail_closed_and_auth_guards() -> None:
    # Missing API key config must fail closed (503)
    unconfigured = TestClient(
        create_orchestrator_app(api_key="", signing_secret=TEST_SIGNING_SECRET)
    )
    assert unconfigured.get("/v1/templates").status_code == 503

    client, _ = _make_client()
    assert client.get("/healthz").status_code == 200
    assert client.get("/v1/templates").status_code == 401
    assert (
        client.get("/v1/templates", headers={"X-Spartan-Orchestrator-Key": "wrong"}).status_code
        == 401
    )
    ok = client.get("/v1/templates", headers={"X-Spartan-Orchestrator-Key": TEST_API_KEY})
    assert ok.status_code == 200
    assert len(ok.json()["templates"]) == 12


def test_provision_hardened_flags_quota_idor_chaos_receipt_and_terminate() -> None:
    client, rt = _make_client()
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    # 1. Provision free-tier sandbox
    res = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "sageideas",
            "user_id": "user_alice",
            "template_id": "lab1-core-engine",
            "tier": "free",
        },
    )
    assert res.status_code == 200
    sbx = res.json()
    sid = sbx["sandbox_id"]
    assert sbx["status"] == "running"
    assert sbx["terminal_token"] is not None

    # Verify terminal token cryptographic binding
    claims = verify_terminal_token(
        secret=TEST_SIGNING_SECRET,
        token=sbx["terminal_token"],
        expected_sandbox_id=sid,
    )
    assert claims is not None
    assert claims["uid"] == "user_alice"
    assert (
        verify_terminal_token(
            secret=TEST_SIGNING_SECRET,
            token=sbx["terminal_token"],
            expected_sandbox_id="sbx_other",
        )
        is None
    )

    # Verify hardened Docker run flags
    cmd = rt.running_containers[sbx["container_name"]]
    assert "--read-only" in cmd
    assert "--cap-drop=ALL" in cmd
    assert "--security-opt=no-new-privileges:true" in cmd
    assert "--pids-limit" in cmd

    # 2. Free tier quota blocks 2nd concurrent sandbox (429)
    dup = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "sageideas",
            "user_id": "user_alice",
            "template_id": "lab2-linux-tls",
            "tier": "free",
        },
    )
    assert dup.status_code == 429

    # 3. Cross-user IDOR attempt returns 403
    idor = client.get(
        f"/v1/sandboxes/{sid}",
        headers=headers,
        params={"tenant_id": "sageideas", "user_id": "user_mallory"},
    )
    assert idor.status_code == 403

    # 4. Blind chaos hides fault name until verified, then issues signed SHA-256 receipt
    chaos = client.post(
        f"/v1/sandboxes/{sid}/chaos",
        headers=headers,
        json={"tenant_id": "sageideas", "user_id": "user_alice", "seed": 7},
    )
    assert chaos.status_code == 200
    assert chaos.json()["status"] == "armed"
    assert "faultId" not in chaos.json()

    verified = client.post(
        f"/v1/sandboxes/{sid}/verify",
        headers=headers,
        json={"tenant_id": "sageideas", "user_id": "user_alice"},
    )
    assert verified.status_code == 200
    vbody = verified.json()
    assert vbody["passed"] is True
    assert vbody["revealed_fault"] is not None
    assert verify_receipt_signature(vbody["receipt"]) is True

    # 5. Terminate tears down container & network
    term = client.delete(
        f"/v1/sandboxes/{sid}",
        headers=headers,
        params={"tenant_id": "sageideas", "user_id": "user_alice"},
    )
    assert term.status_code == 200
    assert term.json()["status"] == "terminated"
    assert sbx["container_name"] not in rt.running_containers


def test_ttl_reaper_cleans_expired_sandboxes() -> None:
    rt = MemorySandboxRuntime()
    app = create_orchestrator_app(
        api_key=TEST_API_KEY,
        signing_secret=TEST_SIGNING_SECRET,
        runtime=rt,
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}
    res = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "sageideas",
            "user_id": "user_bob",
            "template_id": "lab4-rag-acl",
            "tier": "pro",
        },
    )
    sid = res.json()["sandbox_id"]
    service = app.state.orchestrator
    reaped = service.reap_expired(now_epoch=9_999_999_999.0)
    assert sid in reaped
    assert service.active_count() == 0


def test_fly_machines_runtime_boots_probes_and_destroys_firecracker_vm() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_sender(
        method: str, url: str, body: dict[str, object] | None
    ) -> tuple[int, dict[str, object]]:
        calls.append((method, url, body))
        if method == "POST":
            return 200, {"id": "vm_firecracker_01", "state": "started"}
        if method == "GET":
            return 200, {"id": "vm_firecracker_01", "state": "started"}
        return 200, {"ok": True}

    rt = FlyMachinesRuntime(
        app_name="crucible-sandboxes",
        api_token="fly_test_token",
        region="iad",
        http_sender=fake_sender,
    )
    app = create_orchestrator_app(
        api_key=TEST_API_KEY,
        signing_secret=TEST_SIGNING_SECRET,
        runtime=rt,
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    prov = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "crucible",
            "user_id": "user_firecracker",
            "template_id": "lab1-core-engine",
            "tier": "pro",
        },
    )
    assert prov.status_code == 200
    sid = prov.json()["sandbox_id"]
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/apps/crucible-sandboxes/machines")
    assert calls[0][2] is not None
    cfg = calls[0][2]["config"]
    assert isinstance(cfg, dict) and cfg["auto_destroy"] is True

    ver = client.post(
        f"/v1/sandboxes/{sid}/verify",
        headers=headers,
        json={"tenant_id": "crucible", "user_id": "user_firecracker"},
    )
    assert ver.status_code == 200
    assert ver.json()["passed"] is True

    term = client.delete(
        f"/v1/sandboxes/{sid}",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "user_firecracker"},
    )
    assert term.status_code == 200
    assert any(m == "DELETE" and "vm_firecracker_01" in u for m, u, _ in calls)


def test_fly_persistent_volume_pro_auto_provision_and_reuse(tmp_path) -> None:
    """Pro users opting into persist_volume auto-provision & reuse a 2 GB encrypted Fly Volume; Free users cannot."""
    from orchestrator.grader import provision_workspace
    from orchestrator.models import LAB_TEMPLATES, TIER_QUOTAS, ProvisionRequest
    from orchestrator.runtime import FlyMachinesRuntime
    from orchestrator.service import SandboxOrchestratorService

    volumes: list[dict] = []
    machine_payloads: list[dict] = []

    def fake_fly(method: str, url: str, body: dict | None):
        if method == "GET" and url.endswith("/volumes"):
            return 200, list(volumes)
        if method == "POST" and url.endswith("/volumes"):
            vol = {
                "id": f"vol_persist_{len(volumes) + 1}",
                "name": body["name"],
                "region": body["region"],
                "size_gb": body["size_gb"],
                "encrypted": body["encrypted"],
                "state": "created",
                "attached_machine_id": None,
            }
            volumes.append(vol)
            return 200, vol
        if method == "POST" and url.endswith("/machines"):
            machine_payloads.append(body or {})
            return 200, {"id": f"vm_vol_{len(machine_payloads)}", "region": "iad", "state": "started"}
        if method == "DELETE" and "/machines/" in url:
            return 200, {"ok": True}
        return 200, {}

    rt = FlyMachinesRuntime(
        app_name="crucible-sandboxes",
        api_token="fly_test_token",
        region="iad",
        http_sender=fake_fly,
    )
    svc = SandboxOrchestratorService(runtime=rt, signing_secret="super-secret-signing-key-123456")

    # 1. Free user requesting persist_volume must NOT create or mount a paid Fly Volume
    free_sess = svc.provision(
        ProvisionRequest(
            tenant_id="spartan-academy",
            user_id="free_user",
            template_id="lab1-core-engine",
            tier="free",
            persist_volume=True,
        )
    )
    assert free_sess.volume_id is None
    assert len(volumes) == 0
    assert "mounts" not in machine_payloads[-1]["config"]

    # 2. Pro user requesting persist_volume creates a 2 GB encrypted NVMe volume and mounts /workspace-persist
    pro_sess1 = svc.provision(
        ProvisionRequest(
            tenant_id="spartan-academy",
            user_id="pro_user",
            template_id="lab0-free-range",
            tier="pro",
            persist_volume=True,
        )
    )
    assert pro_sess1.volume_id == "vol_persist_1"
    assert len(volumes) == 1
    assert volumes[0]["size_gb"] == 2
    assert volumes[0]["encrypted"] is True
    assert machine_payloads[-1]["config"]["mounts"] == [{"volume": "vol_persist_1", "path": "/workspace-persist"}]
    svc.terminate(sandbox_id=pro_sess1.sandbox_id, tenant_id="spartan-academy", user_id="pro_user")

    # 3. Next Pro session for same user reuses the existing unattached volume (no duplicate billing!)
    pro_sess2 = svc.provision(
        ProvisionRequest(
            tenant_id="spartan-academy",
            user_id="pro_user",
            template_id="lab0-free-range",
            tier="pro",
            persist_volume=True,
        )
    )
    assert pro_sess2.volume_id == "vol_persist_1"
    assert len(volumes) == 1

    # 4. Free-Range Server-Lifecycle starter kit files exist on disk
    provision_workspace(tmp_path, "lab0-free-range", "sbx_test_sl", arm_fault=False)
    sl_dir = tmp_path / "playground" / "server-lifecycle"
    assert (sl_dir / "main.tf").exists()
    assert (sl_dir / "alerts.yml").exists()
    assert (sl_dir / "alerts.test.yml").exists()
    assert (sl_dir / "backup_restore_drill.sh").exists()
    assert "v13" in LAB_TEMPLATES["lab0-free-range"].image
    assert TIER_QUOTAS["pro"].ttl_minutes == 120


def test_sprint_m4_m5_multiregion_preview_allowlist_steps_and_moto(tmp_path) -> None:
    """Verify multi-region Fly routing (iad/ams/sin), port preview SSRF allowlist, step checker, .tf read & Moto AWS helper."""
    from fastapi import HTTPException
    from orchestrator.grader import check_lifecycle_steps, provision_workspace, read_workspace_file
    from orchestrator.models import ProvisionRequest
    from orchestrator.runtime import FlyMachinesRuntime
    from orchestrator.service import SandboxOrchestratorService
    from orchestrator.vm_agent import _fetch_local_preview

    regions_seen: list[str] = []

    def fake_fly(method: str, url: str, body: dict | None):
        if method == "POST" and url.endswith("/machines"):
            reg = (body or {}).get("region", "iad")
            regions_seen.append(reg)
            return 200, {"id": f"vm_{reg}", "region": reg, "state": "started"}
        return 200, {}

    rt = FlyMachinesRuntime(app_name="crucible-sandboxes", api_token="t", region="iad", http_sender=fake_fly)
    svc = SandboxOrchestratorService(runtime=rt, signing_secret="super-secret-signing-key-123456")

    eu_sess = svc.provision(
        ProvisionRequest(
            tenant_id="spartan-academy",
            user_id="eu_user",
            template_id="lab0-free-range",
            tier="pro",
            region="ams",
        )
    )
    ap_sess = svc.provision(
        ProvisionRequest(
            tenant_id="spartan-academy",
            user_id="ap_user",
            template_id="lab0-free-range",
            tier="pro",
            region="sin",
        )
    )
    assert eu_sess.region == "ams"
    assert ap_sess.region == "sin"
    assert regions_seen == ["ams", "sin"]

    # Port preview must block VM agent (:8091) and raw DB (:5432) ports
    for blocked in (8091, 5432, 6379, 22):
        try:
            _fetch_local_preview(blocked, "")
            raise AssertionError(f"Expected port {blocked} to be blocked")
        except HTTPException as exc:
            assert exc.status_code == 403

    # .tf readable via workspace file editor + automation-service + Lab 9 Moto AWS helper seeded
    provision_workspace(tmp_path, "lab0-free-range", "sbx_m5", arm_fault=False)
    tf_read = read_workspace_file(tmp_path, "playground/server-lifecycle/main.tf")
    assert "terraform_data" in tf_read["content"]
    assert (tmp_path / "playground" / "automation-service" / "app.py").exists()
    assert (tmp_path / "playground" / "automation-service" / "test_service.py").exists()
    assert (tmp_path / "bin" / "start-local-aws").exists()

    step_res = check_lifecycle_steps(tmp_path, "T13")
    assert step_res["task_id"] == "T13"
    assert step_res["total_count"] >= 3
    assert any(s["id"] == "auto_present" and s["passed"] for s in step_res["steps"])

    lab9_root = tmp_path / "lab9"
    provision_workspace(lab9_root, "lab9-iac-iam", "sbx_m5_l9", arm_fault=False)
    assert (lab9_root / "terraform" / "local_aws_demo.py").exists()
    assert (lab9_root / "bin" / "start-local-aws").exists()
