"""Security, quota, isolation & lifecycle tests for the Cloud Sandbox Orchestrator."""
from __future__ import annotations

from fastapi.testclient import TestClient

from orchestrator.app import create_orchestrator_app
from orchestrator.runtime import (
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
    assert len(ok.json()["templates"]) == 6


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
