"""Real Linux PTY, secret-stripping, and live SLA fault/fix verification tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from orchestrator.app import create_orchestrator_app
from orchestrator.runtime import LinuxPtySandboxRuntime
from tools.war_room import verify_receipt_signature

TEST_API_KEY = "spartan-super-secret-orchestrator-key-999"
TEST_SIGNING_SECRET = "spartan-super-secret-terminal-signing-999"


def test_linux_pty_executes_real_shell_and_strips_orchestrator_secrets(tmp_path: Path) -> None:
    rt = LinuxPtySandboxRuntime(base_dir=tmp_path)
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
            "user_id": "user_linux",
            "template_id": "lab1-core-engine",
            "tier": "pro",
            "arm_blind_chaos": True,
        },
    )
    assert prov.status_code == 200
    sbx = prov.json()
    sid = sbx["sandbox_id"]
    token = sbx["terminal_token"]
    assert sbx["blind_fault_armed"] is True

    # 1. Verify SLA FAILS while real fault is still broken
    fail_verify = client.post(
        f"/v1/sandboxes/{sid}/verify",
        headers=headers,
        json={"tenant_id": "crucible", "user_id": "user_linux"},
    )
    assert fail_verify.status_code == 200
    assert fail_verify.json()["passed"] is False
    assert "SCAN" in fail_verify.json()["receipt"]["checks"][0]["detail"]

    # 2. Attach real WebSocket PTY, run real shell commands, prove secrets are NOT in env
    with client.websocket_connect(f"/v1/sandboxes/{sid}/terminal?token={token}") as ws:
        banner = ws.receive_text()
        assert "crucible-linux-pty" in banner
        ws.send_text(json.dumps({"type": "input", "data": 'uname -s && env && echo "__DO""NE__"\n'}))
        collected = ""
        for _ in range(30):
            collected += ws.receive_text()
            if "__DONE__" in collected:
                break
        assert "Darwin" in collected or "Linux" in collected
        assert TEST_API_KEY not in collected
        assert TEST_SIGNING_SECRET not in collected
        assert "SPARTAN_ORCHESTRATOR_API_KEY" not in collected

    # 3. Apply the REAL remediation inside the sandbox workspace
    ws_dir = rt.get_workspace_dir(container_name=sbx["container_name"])
    assert ws_dir is not None
    conn = sqlite3.connect(str(ws_dir / "data" / "orders.db"))
    try:
        conn.execute("CREATE INDEX idx_orders_tenant_created ON orders(tenant_id, created_at)")
        conn.commit()
    finally:
        conn.close()
    cfg = ws_dir / "config" / "pgbouncer.ini"
    cfg.write_text(cfg.read_text().replace("default_pool_size = 2", "default_pool_size = 32"))

    # 4. Now verify SLA PASSES and mints a cryptographically verified SHA-256 receipt!
    pass_verify = client.post(
        f"/v1/sandboxes/{sid}/verify",
        headers=headers,
        json={"tenant_id": "crucible", "user_id": "user_linux"},
    )
    assert pass_verify.status_code == 200
    body = pass_verify.json()
    assert body["passed"] is True
    assert body["revealed_fault"] == "pg_missing_index_and_pool_starvation"
    assert verify_receipt_signature(body["receipt"]) is True

    # 5. Terminate cleans up workspace directory
    term = client.delete(
        f"/v1/sandboxes/{sid}",
        headers=headers,
        params={"tenant_id": "crucible", "user_id": "user_linux"},
    )
    assert term.status_code == 200
    assert not ws_dir.exists()


def test_all_six_lab_scenarios_fail_when_armed_and_pass_when_healthy(tmp_path: Path) -> None:
    rt = LinuxPtySandboxRuntime(base_dir=tmp_path)
    app = create_orchestrator_app(
        api_key=TEST_API_KEY,
        signing_secret=TEST_SIGNING_SECRET,
        runtime=rt,
    )
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    templates = [
        "lab1-core-engine",
        "lab2-linux-tls",
        "lab3-lakehouse-wap",
        "lab4-rag-acl",
        "lab5-raft-internals",
        "lab6-k8s-ebpf",
    ]
    for tpl in templates:
        # Clean boot -> healthy
        p = client.post(
            "/v1/sandboxes",
            headers=headers,
            json={"tenant_id": "crucible", "user_id": f"u_{tpl}", "template_id": tpl, "tier": "pro"},
        )
        assert p.status_code == 200
        sid = p.json()["sandbox_id"]
        v_ok = client.post(
            f"/v1/sandboxes/{sid}/verify",
            headers=headers,
            json={"tenant_id": "crucible", "user_id": f"u_{tpl}"},
        )
        assert v_ok.json()["passed"] is True, f"{tpl} healthy baseline failed: {v_ok.json()}"

        # Inject blind chaos -> MUST FAIL until fixed!
        c = client.post(
            f"/v1/sandboxes/{sid}/chaos",
            headers=headers,
            json={"tenant_id": "crucible", "user_id": f"u_{tpl}"},
        )
        assert c.status_code == 200
        v_fail = client.post(
            f"/v1/sandboxes/{sid}/verify",
            headers=headers,
            json={"tenant_id": "crucible", "user_id": f"u_{tpl}"},
        )
        assert v_fail.json()["passed"] is False, f"{tpl} armed fault falsely passed!"

        client.delete(
            f"/v1/sandboxes/{sid}",
            headers=headers,
            params={"tenant_id": "crucible", "user_id": f"u_{tpl}"},
        )
