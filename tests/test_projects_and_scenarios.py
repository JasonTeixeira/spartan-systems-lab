"""Tests for 24-Scenario Fault Catalog, Blind Chaos Roulette, Live Loadgen & Build-From-Scratch Projects."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from orchestrator.app import create_orchestrator_app
from orchestrator.build_projects import BUILD_PROJECTS, run_project_stage_tests, scaffold_project_workspace
from orchestrator.grader import _scrubbed_subprocess_env, _unprivileged_preexec, arm_scenario_fault, list_all_scenarios
from orchestrator.runtime import LinuxPtySandboxRuntime


def test_24_scenario_catalog_and_roulette(tmp_path: Path) -> None:
    catalog = list_all_scenarios()
    total = sum(len(items) for items in catalog.values())
    assert total == 25 or total >= 24, f"Expected >=24 scenarios, got {total}"
    assert len(catalog["lab1-core-engine"]) == 4
    assert len(catalog["lab2-linux-tls"]) == 3

    # Specific scenario mutation works cleanly
    ws = tmp_path / "sbx_s1"
    f = arm_scenario_fault(ws, "lab1-core-engine", "sbx_s1", scenario_id="pgbouncer_session_mode_starvation")
    assert f.fault_id == "pgbouncer_session_mode_starvation"
    assert "pool_mode = session" in (ws / "config" / "pgbouncer.ini").read_text(encoding="utf-8")

    # Random roulette picks a valid scenario from lab1
    f_rand = arm_scenario_fault(ws, "lab1-core-engine", "sbx_s1", scenario_id="random", seed=42)
    valid_ids = {s["scenario_id"] for s in catalog["lab1-core-engine"]}
    assert f_rand.fault_id in valid_ids


def test_all_four_build_from_scratch_projects_starter_vs_reference(tmp_path: Path) -> None:
    assert len(BUILD_PROJECTS) == 4
    for project_id in BUILD_PROJECTS:
        ws = tmp_path / project_id
        # 1. Starter stub fails all 5 stages cleanly
        scaffold_project_workspace(ws, project_id, use_reference=False)
        res_start = run_project_stage_tests(ws, project_id, _scrubbed_subprocess_env, _unprivileged_preexec)
        assert res_start["stages_total"] == 5
        assert res_start["all_passed"] is False
        assert res_start["stages_passed"] == 0

        # 2. Reference implementation passes ALL 5/5 stages cleanly!
        scaffold_project_workspace(ws, project_id, use_reference=True)
        res_ref = run_project_stage_tests(ws, project_id, _scrubbed_subprocess_env, _unprivileged_preexec)
        assert res_ref["all_passed"] is True, f"{project_id} failed stages: {res_ref}"
        assert res_ref["stages_passed"] == 5


def test_orchestrator_endpoints_scenarios_loadgen_and_project_runner(tmp_path: Path) -> None:
    rt = LinuxPtySandboxRuntime(base_dir=tmp_path)
    app = create_orchestrator_app(
        api_key="test-key-1234567890",
        signing_secret="signing-secret-1234567890",
        runtime=rt,
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": "test-key-1234567890"}

    # 1. Scenarios & build projects catalog
    cat = client.get("/v1/scenarios", headers=headers)
    assert cat.status_code == 200
    body = cat.json()
    assert len(body["projects"]) == 4
    assert sum(len(v) for v in body["scenarios"].values()) >= 24

    # 2. Provision sandbox with Blind Roulette scenario
    prov = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "spartan-academy",
            "user_id": "u_builder",
            "template_id": "lab1-core-engine",
            "tier": "pro",
            "arm_blind_chaos": True,
            "scenario_id": "random",
        },
    )
    assert prov.status_code == 200
    sid = prov.json()["sandbox_id"]

    # 3. Live Loadgen toggle on/off + cross-user IDOR guard
    lg_on = client.post(
        f"/v1/sandboxes/{sid}/loadgen",
        headers=headers,
        json={"tenant_id": "spartan-academy", "user_id": "u_builder", "enabled": True, "rps": 50},
    )
    assert lg_on.status_code == 200
    assert lg_on.json()["loadgen"]["active"] is True

    idor = client.post(
        f"/v1/sandboxes/{sid}/loadgen",
        headers=headers,
        json={"tenant_id": "spartan-academy", "user_id": "u_attacker", "enabled": True, "rps": 50},
    )
    assert idor.status_code == 403

    # 4. Build-From-Scratch project scaffold + test via orchestrator API
    scaf = client.post(
        f"/v1/sandboxes/{sid}/project",
        headers=headers,
        json={
            "tenant_id": "spartan-academy",
            "user_id": "u_builder",
            "action": "scaffold",
            "project_id": "proj-redis-limiter",
            "use_reference": True,
        },
    )
    assert scaf.status_code == 200
    assert scaf.json()["entry_file"] == "build/redis_limiter.py"

    run_res = client.post(
        f"/v1/sandboxes/{sid}/project",
        headers=headers,
        json={
            "tenant_id": "spartan-academy",
            "user_id": "u_builder",
            "action": "test",
            "project_id": "proj-redis-limiter",
        },
    )
    assert run_res.status_code == 200
    assert run_res.json()["all_passed"] is True
    assert run_res.json()["stages_passed"] == 5

    # Clean up
    client.delete(
        f"/v1/sandboxes/{sid}",
        headers=headers,
        params={"tenant_id": "spartan-academy", "user_id": "u_builder"},
    )


def test_fly_warm_pool_claim_and_skip_launch() -> None:
    from orchestrator.models import LAB_TEMPLATES, TIER_QUOTAS
    from orchestrator.runtime import FlyMachinesRuntime

    calls: list[tuple[str, str, dict | None]] = []

    def fake_fly_api(method: str, path: str, body: dict | None):
        calls.append((method, path, body))
        if method == "GET" and path.endswith("/machines"):
            return 200, [
                {
                    "id": "warm_m_01",
                    "state": "stopped",
                    "region": "iad",
                    "private_ip": "fdaa::warm1",
                    "config": {
                        "image": "registry.fly.io/crucible-sandboxes:v4",
                        "metadata": {"crucible_pool": "warm"},
                    },
                }
            ]
        if method == "POST" and path.endswith("/machines/warm_m_01/lease"):
            return 200, {"status": "ok", "data": {"nonce": "lease_nonce_xyz"}}
        if method == "DELETE" and path.endswith("/machines/warm_m_01/lease"):
            return 200, {"status": "ok"}
        if method == "POST" and path.endswith("/machines/warm_m_01"):
            return 200, {"id": "warm_m_01", "state": "starting", "region": "iad", "private_ip": "fdaa::warm1", "instance_id": "inst_1"}
        if method == "POST" and path.endswith("/machines/warm_m_01/start"):
            return 200, {"ok": True}
        if method == "POST" and path.endswith("/machines"):
            return 200, {"id": "warm_m_02", "region": "iad"}
        return 200, {}

    rt = FlyMachinesRuntime(
        app_name="crucible-sandboxes",
        api_token="tok_test",
        region="iad",
        image_override="registry.fly.io/crucible-sandboxes:v4",
        warm_pool_size=2,
        http_sender=fake_fly_api,
    )
    res = rt.start_sandbox(
        sandbox_id="sbx_warmtest",
        tenant_id="spartan-academy",
        container_name="spartan-sbx_warmtest",
        network_name="net-sbx_warmtest",
        template=LAB_TEMPLATES["lab1-core-engine"],
        quota=TIER_QUOTAS["pro"],
        expires_epoch=9999999999,
        vm_secret="fresh_ephemeral_secret",
        arm_blind_chaos=True,
    )
    assert res.machine_id == "warm_m_01"
    assert any(m == "POST" and p.endswith("/machines/warm_m_01/lease") for m, p, _ in calls)
    assert any(m == "POST" and p.endswith("/machines/warm_m_01") for m, p, _ in calls)
    assert any(m == "DELETE" and p.endswith("/machines/warm_m_01/lease") for m, p, _ in calls)
    # Verify ensure_warm_pool creates replacement with skip_launch=True ($0 idle compute)
    pool_res = rt.ensure_warm_pool(target_size=2)
    assert pool_res["created"] == 1
    create_call = next(b for m, p, b in calls if m == "POST" and p.endswith("/machines"))
    assert create_call["skip_launch"] is True
    assert create_call["config"]["auto_destroy"] is False
    assert create_call["config"]["metadata"]["crucible_pool"] == "warm"
