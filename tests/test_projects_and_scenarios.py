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
    assert total >= 28, f"Expected >=28 scenarios (incl Sprint 2 deep chaos), got {total}"
    assert len(catalog["lab1-core-engine"]) == 5
    assert len(catalog["lab2-linux-tls"]) == 4
    assert len(catalog["lab5-raft-internals"]) == 3
    assert len(catalog["lab7-linux-sre"]) == 3

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

    # 4. Live Prometheus scrape endpoint
    prom_res = client.get(
        f"/v1/sandboxes/{sid}/metrics/prometheus",
        headers=headers,
        params={"tenant_id": "spartan-academy", "user_id": "u_builder"},
    )
    assert prom_res.status_code == 200
    assert "# HELP crucible_sla_latency_ms" in prom_res.text
    assert "# TYPE crucible_sla_latency_ms gauge" in prom_res.text

    # 5. Build-From-Scratch project scaffold + test via orchestrator API
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


def test_sprint2_deep_systems_chaos_scenarios(tmp_path: Path) -> None:
    import json
    from orchestrator.grader import verify_workspace_checks

    # 1. Postgres MVCC / WAL bloat
    ws1 = tmp_path / "mvcc"
    arm_scenario_fault(ws1, "lab1-core-engine", "sbx_mvcc", scenario_id="pg_wal_bloat_and_vacuum_freeze")
    ok1, _, checks1 = verify_workspace_checks(ws1, "lab1-core-engine")
    assert ok1 is False
    assert any(c["id"] == "pg_mvcc_wal" and not c["passed"] for c in checks1)

    # 2. TCP tc-netem packet loss + BBR
    ws2 = tmp_path / "netem"
    arm_scenario_fault(ws2, "lab2-linux-tls", "sbx_netem", scenario_id="tc_netem_packet_loss_tail_collapse")
    ok2, _, checks2 = verify_workspace_checks(ws2, "lab2-linux-tls")
    assert ok2 is False
    assert any(c["id"] == "tcp_netem_bbr" and not c["passed"] for c in checks2)
    (ws2 / "config" / "netem.conf").write_text("loss_pct = 0.0\ndelay_ms = 5\ncongestion_control = bbr\n", encoding="utf-8")
    _, _, checks2_fix = verify_workspace_checks(ws2, "lab2-linux-tls")
    assert any(c["id"] == "tcp_netem_bbr" and c["passed"] for c in checks2_fix)

    # 3. Raft / Kafka ISR durability + fencing
    ws5 = tmp_path / "isr"
    arm_scenario_fault(ws5, "lab5-raft-internals", "sbx_isr", scenario_id="raft_isr_lag_and_fencing_storm")
    ok5, _, checks5 = verify_workspace_checks(ws5, "lab5-raft-internals")
    assert ok5 is False
    assert any(c["id"] == "raft_isr" and not c["passed"] for c in checks5)
    (ws5 / "raft" / "cluster.json").write_text(
        json.dumps({"replication_factor": 3, "min_insync_replicas": 2, "acks": "all", "unclean_leader_election": False}),
        encoding="utf-8",
    )
    _, _, checks5_fix = verify_workspace_checks(ws5, "lab5-raft-internals")
    assert any(c["id"] == "raft_isr" and c["passed"] for c in checks5_fix)

    # 4. Linux cgroup v2 OOM + CFS throttle
    ws7 = tmp_path / "cgroup"
    arm_scenario_fault(ws7, "lab7-linux-sre", "sbx_cg", scenario_id="cgroup_oom_kill_and_cpu_throttle")
    ok7, _, checks7 = verify_workspace_checks(ws7, "lab7-linux-sre")
    assert ok7 is False
    assert any(c["id"] == "linux_cgroup" and not c["passed"] for c in checks7)
    (ws7 / "config" / "cgroup.conf").write_text("memory_max_mb = 1024\ncpu_quota_us = 100000\ncpu_period_us = 100000\n", encoding="utf-8")
    _, _, checks7_fix = verify_workspace_checks(ws7, "lab7-linux-sre")
    assert any(c["id"] == "linux_cgroup" and c["passed"] for c in checks7_fix)
