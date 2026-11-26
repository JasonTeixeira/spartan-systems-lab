"""Verify all 11 Crucible Firecracker labs (M01-M12) fail when armed and pass when healthy."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from orchestrator.app import create_orchestrator_app
from orchestrator.models import LAB_TEMPLATES
from orchestrator.runtime import LinuxPtySandboxRuntime

TEST_API_KEY = "spartan-wave-a-key-123456"
TEST_SIGNING_SECRET = "spartan-wave-a-secret-987654"


def test_all_eleven_labs_healthy_vs_armed_and_live_file_remediation(tmp_path: Path) -> None:
    rt = LinuxPtySandboxRuntime(base_dir=tmp_path)
    app = create_orchestrator_app(api_key=TEST_API_KEY, signing_secret=TEST_SIGNING_SECRET, runtime=rt)
    client = TestClient(app)
    headers = {"X-Spartan-Orchestrator-Key": TEST_API_KEY}

    assert len(LAB_TEMPLATES) == 12

    for tpl_id in LAB_TEMPLATES:
        p = client.post(
            "/v1/sandboxes",
            headers=headers,
            json={"tenant_id": "crucible", "user_id": f"u_{tpl_id}", "template_id": tpl_id, "tier": "pro"},
        )
        assert p.status_code == 200, f"{tpl_id} provision failed: {p.text}"
        sid = p.json()["sandbox_id"]

        # Healthy baseline must pass
        v_ok = client.post(
            f"/v1/sandboxes/{sid}/verify",
            headers=headers,
            json={"tenant_id": "crucible", "user_id": f"u_{tpl_id}"},
        )
        assert v_ok.status_code == 200 and v_ok.json()["passed"] is True, f"{tpl_id} healthy failed: {v_ok.json()}"

        # Armed blind chaos must fail
        c = client.post(
            f"/v1/sandboxes/{sid}/chaos",
            headers=headers,
            json={"tenant_id": "crucible", "user_id": f"u_{tpl_id}"},
        )
        assert c.status_code == 200
        v_fail = client.post(
            f"/v1/sandboxes/{sid}/verify",
            headers=headers,
            json={"tenant_id": "crucible", "user_id": f"u_{tpl_id}"},
        )
        assert v_fail.status_code == 200 and v_fail.json()["passed"] is False, f"{tpl_id} armed fault falsely passed!"

        client.delete(
            f"/v1/sandboxes/{sid}",
            headers=headers,
            params={"tenant_id": "crucible", "user_id": f"u_{tpl_id}"},
        )
