"""Red-team anti-cheat, per-VM secret isolation, and stateless Firecracker tests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from orchestrator.app import create_orchestrator_app
from orchestrator.runtime import FlyMachinesRuntime, LinuxPtySandboxRuntime
from orchestrator.store import InMemorySessionStore

TEST_API_KEY = "spartan-redteam-api-key-123456"
TEST_SIGNING_SECRET = "spartan-redteam-signing-secret-987654"


def test_redteam_tampering_with_user_test_files_cannot_cheat_grader(tmp_path: Path) -> None:
    """Overwriting rag/test_acl.py or raft/test_fencing.py must NOT bypass immutable hidden grading."""
    rt = LinuxPtySandboxRuntime(base_dir=tmp_path)
    app = create_orchestrator_app(
        api_key=TEST_API_KEY, signing_secret=TEST_SIGNING_SECRET, runtime=rt
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    # Lab 4: armed broken ACL -> overwrite rag/test_acl.py with fake PASS -> MUST STILL FAIL!
    p4 = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "crucible",
            "user_id": "cheater_1",
            "template_id": "lab4-rag-acl",
            "tier": "pro",
            "arm_blind_chaos": True,
        },
    ).json()
    ws4 = rt.get_workspace_dir(container_name=p4["container_name"])
    assert ws4 is not None
    (ws4 / "rag" / "test_acl.py").write_text('print("PASS: fake")\n', encoding="utf-8")
    v4 = client.post(
        f"/v1/sandboxes/{p4['sandbox_id']}/verify",
        headers=headers,
        json={"tenant_id": "crucible", "user_id": "cheater_1"},
    ).json()
    assert v4["passed"] is False, "Cheater bypassed Lab 4 grader by editing rag/test_acl.py!"

    # Lab 5: armed broken Raft guard -> overwrite raft/test_fencing.py -> MUST STILL FAIL!
    p5 = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "crucible",
            "user_id": "cheater_2",
            "template_id": "lab5-raft-internals",
            "tier": "pro",
            "arm_blind_chaos": True,
        },
    ).json()
    ws5 = rt.get_workspace_dir(container_name=p5["container_name"])
    assert ws5 is not None
    (ws5 / "raft" / "test_fencing.py").write_text('print("PASS: fake")\n', encoding="utf-8")
    v5 = client.post(
        f"/v1/sandboxes/{p5['sandbox_id']}/verify",
        headers=headers,
        json={"tenant_id": "crucible", "user_id": "cheater_2"},
    ).json()
    assert v5["passed"] is False, "Cheater bypassed Lab 5 grader by editing raft/test_fencing.py!"


def test_redteam_verify_subprocess_scrubs_orchestrator_secrets(tmp_path: Path, monkeypatch: Any) -> None:
    """Even if a student puts secret-exfiltration code in publish_gate.py, verify subprocess sees ZERO secrets."""
    monkeypatch.setenv("SPARTAN_ORCHESTRATOR_API_KEY", "TOP_SECRET_ORCH_KEY_DO_NOT_LEAK")
    monkeypatch.setenv("FLY_API_TOKEN", "TOP_SECRET_FLY_TOKEN_DO_NOT_LEAK")

    rt = LinuxPtySandboxRuntime(base_dir=tmp_path)
    app = create_orchestrator_app(
        api_key=TEST_API_KEY, signing_secret=TEST_SIGNING_SECRET, runtime=rt
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    p3 = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "crucible",
            "user_id": "attacker_rce",
            "template_id": "lab3-lakehouse-wap",
            "tier": "pro",
            "arm_blind_chaos": True,
        },
    ).json()
    ws3 = rt.get_workspace_dir(container_name=p3["container_name"])
    assert ws3 is not None
    leak_file = tmp_path / "exfil.txt"
    (ws3 / "wap" / "publish_gate.py").write_text(
        f"import os, pathlib\npathlib.Path({str(leak_file)!r}).write_text(str(dict(os.environ)))\n",
        encoding="utf-8",
    )
    v3 = client.post(
        f"/v1/sandboxes/{p3['sandbox_id']}/verify",
        headers=headers,
        json={"tenant_id": "crucible", "user_id": "attacker_rce"},
    ).json()
    assert v3["passed"] is False
    if leak_file.exists():
        dumped = leak_file.read_text(encoding="utf-8")
        assert "TOP_SECRET_ORCH_KEY_DO_NOT_LEAK" not in dumped
        assert "TOP_SECRET_FLY_TOKEN_DO_NOT_LEAK" not in dumped
        assert "SPARTAN_ORCHESTRATOR_API_KEY" not in dumped
        assert "FLY_API_TOKEN" not in dumped


def test_firecracker_per_vm_ephemeral_secret_and_stateless_replica_handoff() -> None:
    """Two independent stateless orchestrator replicas sharing one Store manage the same Firecracker VM cleanly."""
    shared_store = InMemorySessionStore()
    fly_calls: list[tuple[str, str, dict[str, Any] | None]] = []
    vm_calls: list[tuple[str, str, dict[str, str], dict[str, Any] | None]] = []

    def fake_fly(method: str, url: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        fly_calls.append((method, url, body))
        if method == "POST":
            return 200, {"id": "e82d99aa11bb22", "region": "iad", "state": "started"}
        return 200, {"ok": True}

    def fake_vm(
        method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        vm_calls.append((method, url, headers, body))
        if url.endswith("/internal/health"):
            return 200, {"status": "ok", "ready": True, "daemons": {"postgresql": True, "pgbouncer": True}}
        if url.endswith("/internal/metrics"):
            return 200, {"backend": "fly-firecracker", "real_daemons": True, "daemons": {"postgresql": True}}
        if url.endswith("/internal/verify"):
            return 200, {"passed": True, "detail": "LIVE Postgres 16 Index Scan verified"}
        return 200, {"ok": True}

    rt1 = FlyMachinesRuntime(
        app_name="crucible-sandboxes",
        api_token="fly_tok",
        http_sender=fake_fly,
        vm_http_sender=fake_vm,
    )
    rt2 = FlyMachinesRuntime(
        app_name="crucible-sandboxes",
        api_token="fly_tok",
        http_sender=fake_fly,
        vm_http_sender=fake_vm,
    )
    replica_a = TestClient(
        create_orchestrator_app(
            api_key=TEST_API_KEY, signing_secret=TEST_SIGNING_SECRET, runtime=rt1, store=shared_store
        )
    )
    replica_b = TestClient(
        create_orchestrator_app(
            api_key=TEST_API_KEY, signing_secret=TEST_SIGNING_SECRET, runtime=rt2, store=shared_store
        )
    )
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    # Provision on Replica A
    prov = replica_a.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "spartan-academy",
            "user_id": "user_scale_1",
            "template_id": "lab1-core-engine",
            "tier": "pro",
        },
    )
    assert prov.status_code == 200
    sbx = prov.json()
    sid = sbx["sandbox_id"]
    assert sbx["fly_machine_id"] == "e82d99aa11bb22"
    assert sbx["backend"] == "fly"

    # Prove Fly Machine payload contains per-VM secret and ZERO global orchestrator secrets!
    boot_body = fly_calls[0][2]
    assert boot_body is not None
    vm_env = boot_body["config"]["env"]
    assert "VM_SESSION_SECRET" in vm_env and len(vm_env["VM_SESSION_SECRET"]) >= 32
    assert vm_env["VM_SESSION_SECRET"] != TEST_SIGNING_SECRET
    assert "SPARTAN_ORCHESTRATOR_API_KEY" not in vm_env
    assert "FLY_API_TOKEN" not in vm_env

    # Verify, fetch metrics, list in admin, and force-kill from DIFFERENT Replica B (proving stateless scale!)
    met = replica_b.get(
        f"/v1/sandboxes/{sid}/metrics",
        headers=headers,
        params={"tenant_id": "spartan-academy", "user_id": "user_scale_1"},
    )
    assert met.status_code == 200
    assert met.json()["real_daemons"] is True

    ver = replica_b.post(
        f"/v1/sandboxes/{sid}/verify",
        headers=headers,
        json={"tenant_id": "spartan-academy", "user_id": "user_scale_1"},
    )
    assert ver.status_code == 200
    assert ver.json()["passed"] is True

    adm_list = replica_b.get("/v1/admin/sandboxes", headers=headers)
    assert adm_list.status_code == 200
    assert adm_list.json()["activeSandboxes"] == 1

    adm_kill = replica_b.delete(f"/v1/admin/sandboxes/{sid}", headers=headers)
    assert adm_kill.status_code == 200
    assert adm_kill.json()["status"] == "terminated"
    assert any(m == "DELETE" and "e82d99aa11bb22" in u for m, u, _ in fly_calls)


def test_live_file_editor_strict_path_containment_and_granular_checks(tmp_path: Path) -> None:
    """File editor allows safe config edits, blocks path traversal (../), and updates granular checks live."""
    rt = LinuxPtySandboxRuntime(base_dir=tmp_path)
    app = create_orchestrator_app(
        api_key=TEST_API_KEY, signing_secret=TEST_SIGNING_SECRET, runtime=rt
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    sbx = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "crucible",
            "user_id": "editor_user",
            "template_id": "lab6-k8s-ebpf",
            "tier": "pro",
            "arm_blind_chaos": True,
        },
    ).json()
    sid = sbx["sandbox_id"]

    # 1. List editable files
    flist = client.get(
        f"/v1/sandboxes/{sid}/files",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "editor_user"},
    )
    assert flist.status_code == 200
    paths = [f["path"] for f in flist.json()["files"]]
    assert "k8s/networkpolicy.yaml" in paths
    assert "k8s/pdb.yaml" in paths

    # 2. Path traversal attack MUST be rejected with 400
    trav = client.get(
        f"/v1/sandboxes/{sid}/files/read",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "editor_user", "path": "../../etc/passwd"},
    )
    assert trav.status_code == 400

    # 3. Fix only networkpolicy.yaml via file editor -> granular checks show 1/2 passing!
    rd = client.get(
        f"/v1/sandboxes/{sid}/files/read",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "editor_user", "path": "k8s/networkpolicy.yaml"},
    ).json()
    fixed_np = rd["content"].replace(
        "# BUG: PgBouncer port 6432 is blocked!",
        "- protocol: TCP\n        port: 6432",
    )
    wr = client.put(
        f"/v1/sandboxes/{sid}/files/write",
        headers=headers,
        json={
            "tenant_id": "crucible",
            "user_id": "editor_user",
            "path": "k8s/networkpolicy.yaml",
            "content": fixed_np,
            "reload": True,
        },
    )
    assert wr.status_code == 200
    tel = wr.json()["telemetry"]
    assert tel["checks_passing"] == 1 and tel["checks_total"] == 2
    assert tel["healthy"] is False

    # 4. Fix pdb.yaml -> granular checks flip 2/2 passing!
    rd_pdb = client.get(
        f"/v1/sandboxes/{sid}/files/read",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "editor_user", "path": "k8s/pdb.yaml"},
    ).json()
    wr2 = client.put(
        f"/v1/sandboxes/{sid}/files/write",
        headers=headers,
        json={
            "tenant_id": "crucible",
            "user_id": "editor_user",
            "path": "k8s/pdb.yaml",
            "content": rd_pdb["content"].replace("100%", "75%"),
            "reload": True,
        },
    )
    assert wr2.status_code == 200
    assert wr2.json()["telemetry"]["checks_passing"] == 2
    assert wr2.json()["telemetry"]["healthy"] is True


def test_sprint_m0_vm_root_rce_and_egress_hardening(tmp_path: Path) -> None:
    """Sprint M0 security lock: no root RCE via worker/nginx/daemons/postgres trust + egress firewall."""
    grader_src = (Path(__file__).resolve().parent.parent / "orchestrator" / "grader.py").read_text(encoding="utf-8")
    scenarios_src = (Path(__file__).resolve().parent.parent / "orchestrator" / "scenarios_expanded.py").read_text(encoding="utf-8")
    agent_src = (Path(__file__).resolve().parent.parent / "orchestrator" / "vm_agent.py").read_text(encoding="utf-8")

    # 1. Postgres superuser TCP trust must be removed; pgvector SQL must run as operator
    assert "host all all 127.0.0.1/32 trust" not in grader_src
    assert "local all postgres peer" in grader_src
    assert "user=operator dbname=orders" in grader_src

    # 2. nginx -t must block load_module and run unprivileged with scrubbed env
    assert "load_module" in grader_src
    assert "preexec_fn=_unprivileged_preexec()" in grader_src

    # 3. lab7 bin/run-worker.py must run with scrubbed env (never leaking VM_SESSION_SECRET)
    assert "safe_env = {" in scenarios_src
    assert 'pwd.getpwnam("operator")' in scenarios_src

    # 4. vm_agent must invoke _try_harden_egress_firewall blocking Fly 6PN lateral scan & mining ports
    assert "def _try_harden_egress_firewall" in agent_src
    assert "_try_harden_egress_firewall()" in agent_src
    assert "fdaa::/16" in agent_src
    assert "169.254.169.254/32" in agent_src


def test_sprint_m1_terminal_token_reissue_extend_and_o1_polling() -> None:
    """Sprint M1: refresh token re-issue, +60m extend, tmux PTY, WS metrics push, no O(N^2) reap on reads."""
    from fastapi.testclient import TestClient
    from orchestrator.app import create_orchestrator_app
    from orchestrator.runtime import MemorySandboxRuntime

    app = create_orchestrator_app(
        runtime=MemorySandboxRuntime(),
        api_key="test-key-0123456789",
        signing_secret="test-secret-0123456789",
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": "test-key-0123456789"}

    prov = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={"tenant_id": "crucible", "user_id": "u_m1", "template_id": "lab1-core-engine", "tier": "pro"},
    )
    assert prov.status_code == 200
    sbx = prov.json()
    sid = sbx["sandbox_id"]

    # Refresh flow: GET /v1/sandboxes omits token -> POST /terminal-token re-issues valid token
    listed = client.get("/v1/sandboxes", headers=headers, params={"tenant_id": "crucible", "user_id": "u_m1"}).json()
    assert listed["sandboxes"][0]["terminal_token"] is None

    reissued = client.post(
        f"/v1/sandboxes/{sid}/terminal-token",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "u_m1"},
    )
    assert reissued.status_code == 200
    tok = reissued.json()["terminal_token"]
    assert tok and reissued.json()["ttl_remaining_seconds"] > 0

    # Cross-user token re-issue must fail closed (403)
    bad = client.post(
        f"/v1/sandboxes/{sid}/terminal-token",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "attacker"},
    )
    assert bad.status_code == 403

    # +60m TTL extend succeeds and advances expiry
    ext = client.post(
        f"/v1/sandboxes/{sid}/extend",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "u_m1", "extra_minutes": 60},
    )
    assert ext.status_code == 200
    assert ext.json()["ttl_remaining_seconds"] > reissued.json()["ttl_remaining_seconds"] + 3000

    # Verify tmux & WS metrics push & no metrics-poll last_activity reset in vm_agent.py
    agent_src = (Path(__file__).resolve().parent.parent / "orchestrator" / "vm_agent.py").read_text(encoding="utf-8")
    assert '"tmux", "new-session", "-A", "-s", "crucible"' in agent_src
    assert "_push_metrics_over_ws" in agent_src
    assert "def internal_extend" in agent_src
    # Verify service.py no longer calls reap_expired() on every request
    service_src = (Path(__file__).resolve().parent.parent / "orchestrator" / "service.py").read_text(encoding="utf-8")
    assert service_src.count("self.reap_expired()") == 0


def test_free_range_sandbox_snapshots_restore_and_factory_reset(tmp_path: Path) -> None:
    """Free-Range Cloud Range boots with playground files, saves/restores checkpoints, and resets cleanly."""
    from orchestrator.models import LAB_TEMPLATES, TIER_QUOTAS
    from orchestrator.runtime import build_fly_machine_payload

    rt = LinuxPtySandboxRuntime(base_dir=tmp_path)
    app = create_orchestrator_app(
        api_key=TEST_API_KEY, signing_secret=TEST_SIGNING_SECRET, runtime=rt
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    # Verify Fly Machine payload mounts persistent Fly Volume when volume_id is passed
    vol_payload = build_fly_machine_payload(
        sandbox_id="sbx_vol_test",
        tenant_id="spartan-academy",
        container_name="sbx-vol-test",
        template=LAB_TEMPLATES["lab0-free-range"],
        quota=TIER_QUOTAS["pro"],
        expires_epoch=9999999999,
        volume_id="vol_abc123",
    )
    assert vol_payload["config"]["mounts"] == [{"volume": "vol_abc123", "path": "/workspace-persist"}]

    # Provision Free-Range Enterprise Cloud Range
    prov = client.post(
        "/v1/sandboxes",
        headers=headers,
        json={
            "tenant_id": "spartan-academy",
            "user_id": "u_free_range",
            "template_id": "lab0-free-range",
            "tier": "pro",
        },
    )
    assert prov.status_code == 200
    sid = prov.json()["sandbox_id"]

    # Edit playground/experiment.py and save a named checkpoint
    w1 = client.put(
        f"/v1/sandboxes/{sid}/files/write",
        headers=headers,
        json={
            "tenant_id": "spartan-academy",
            "user_id": "u_free_range",
            "path": "playground/experiment.py",
            "content": "print('checkpoint-v1-state')\n",
            "reload": False,
        },
    )
    assert w1.status_code == 200

    snap = client.post(
        f"/v1/sandboxes/{sid}/snapshots",
        headers=headers,
        json={"tenant_id": "spartan-academy", "user_id": "u_free_range", "name": "before-chaos"},
    )
    assert snap.status_code == 200
    assert any(s["name"] == "before-chaos" for s in snap.json()["snapshots"])

    # Break playground/experiment.py
    w2 = client.put(
        f"/v1/sandboxes/{sid}/files/write",
        headers=headers,
        json={
            "tenant_id": "spartan-academy",
            "user_id": "u_free_range",
            "path": "playground/experiment.py",
            "content": "BROKEN_STATE\n",
            "reload": False,
        },
    )
    assert w2.status_code == 200

    # Restore named checkpoint -> original content returns!
    rest = client.post(
        f"/v1/sandboxes/{sid}/snapshots/before-chaos/restore",
        headers=headers,
        json={"tenant_id": "spartan-academy", "user_id": "u_free_range"},
    )
    assert rest.status_code == 200
    r_after = client.get(
        f"/v1/sandboxes/{sid}/files/read",
        headers=headers,
        params={"tenant_id": "spartan-academy", "user_id": "u_free_range", "path": "playground/experiment.py"},
    )
    assert r_after.status_code == 200
    assert "checkpoint-v1-state" in r_after.json()["content"]

    # 1-Click Factory Reset -> restores pristine Free-Range starter file!
    rst = client.post(
        f"/v1/sandboxes/{sid}/reset",
        headers=headers,
        json={"tenant_id": "spartan-academy", "user_id": "u_free_range"},
    )
    assert rst.status_code == 200
    r_pristine = client.get(
        f"/v1/sandboxes/{sid}/files/read",
        headers=headers,
        params={"tenant_id": "spartan-academy", "user_id": "u_free_range", "path": "playground/experiment.py"},
    )
    assert "Crucible Free-Range Cloud VM ready!" in r_pristine.json()["content"]
