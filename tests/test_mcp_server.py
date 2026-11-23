import asyncio
import json
from pathlib import Path

import pytest

from mcp_server.core import (
    build_dashboard_pack,
    export_infra_to_archos_canvas,
    lookup_archos_canvases,
    lookup_toolbelt_and_runbooks,
    run_finops_estimate,
    visualize_infra_and_cicd,
)
from mcp_server.server import mcp


def test_mcp_server_registers_all_7_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    expected = {
        "finops_estimate",
        "toolbelt_and_runbook_lookup",
        "qa_and_code_review",
        "generate_dashboard_pack",
        "visualize_infra_and_cicd",
        "archos_canvas_lookup",
        "infra_to_archos_canvas",
    }
    assert expected.issubset(tool_names)


def test_finops_estimate_all_modes() -> None:
    sys_res = run_finops_estimate(
        mode="system",
        params={"rps": 500, "avg_latency_ms": 100, "payload_kb": 2},
    )
    assert sys_res["result"]["peak_rps"] == 1500.0

    llm_res = run_finops_estimate(
        mode="llm",
        params={
            "monthly_queries": 100_000,
            "avg_input_tokens": 1000,
            "avg_output_tokens": 300,
            "price_per_1m_in": 3.0,
            "price_per_1m_out": 15.0,
        },
    )
    assert llm_res["result"]["savings_pct"] > 50.0

    gpu_res = run_finops_estimate(mode="gpu", params={"params_b": 70, "quant_bits": 4})
    assert gpu_res["result"]["weights_gb"] == 35.0


def test_toolbelt_and_runbook_lookup_finds_react_and_failures() -> None:
    res = lookup_toolbelt_and_runbooks(query="react native", scope="toolbelt")
    assert res["match_count"] >= 1
    assert any("TOOLBELT.md" in m["file"] for m in res["matches"])

    fail_res = lookup_toolbelt_and_runbooks(query="write skew", scope="failures")
    assert fail_res["match_count"] >= 1


def test_generate_dashboard_pack_enforces_approval_and_traversal_guards(tmp_path: Path) -> None:
    preview = build_dashboard_pack(service_name="Billing API", metric_prefix="billing")
    assert preview["dry_run"] is True
    assert preview["written_files"] == []
    assert len(preview["grafana_dashboard"]["panels"]) == 4
    assert "v_exec_billing_kpi" in preview["exec_kpi_sql"]

    # Must block write without explicit confirm_write=True
    with pytest.raises(PermissionError):
        build_dashboard_pack(
            service_name="Billing API",
            dry_run=False,
            confirm_write=False,
            workspace_root=tmp_path,
        )

    # Must block directory traversal
    with pytest.raises(ValueError):
        build_dashboard_pack(
            service_name="Billing API",
            dry_run=False,
            confirm_write=True,
            output_dir="../../escape",
            workspace_root=tmp_path,
        )

    # Succeeds safely inside tmp_path with explicit approval
    written = build_dashboard_pack(
        service_name="Billing API",
        metric_prefix="billing",
        dry_run=False,
        confirm_write=True,
        output_dir="out_dash",
        workspace_root=tmp_path,
    )
    assert len(written["written_files"]) == 2
    assert (tmp_path / "out_dash" / "billing-api_grafana.json").exists()
    assert (tmp_path / "out_dash" / "billing-api_exec_kpi.sql").exists()


def test_visualize_infra_and_cicd_parses_real_lab1_and_ci() -> None:
    res = visualize_infra_and_cicd()
    assert res["services_count"] == 11
    assert "spartan_overview" not in res["infra_mermaid"]
    assert "postgres" in res["infra_mermaid"]
    assert "metabase" in res["infra_d2"]
    assert "quality_and_tests" in res["cicd_mermaid"]


def test_archos_canvas_lookup_reads_manifest_and_handles_missing(tmp_path: Path) -> None:
    # Graceful fallback when ArchOS is absent (e.g., on GitHub Actions Linux runner)
    missing = lookup_archos_canvases(query="mcp", archos_root=tmp_path / "nonexistent")
    assert missing["available"] is False
    assert missing["match_count"] == 0

    # Reads synthetic manifest cleanly
    kdir = tmp_path / "knowledge"
    ddir = kdir / "diagrams"
    ddir.mkdir(parents=True)
    (ddir / "dgm_tool-gateway-mcp.canvas.json").write_text("{}", encoding="utf-8")
    manifest = {
        "folders": [
            {"id": "lib-ai-agents", "title": "AI and agents"},
            {"id": "lib-foundations", "title": "Foundations"},
        ],
        "diagrams": {
            "lib-ai-agents": ["dgm_tool-gateway-mcp", "dgm_llm-attention-and-kv-cache"],
            "lib-foundations": ["dgm_request-lifecycle"],
        },
    }
    (kdir / "library.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    found = lookup_archos_canvases(query="mcp", folder="ai", archos_root=tmp_path)
    assert found["available"] is True
    assert found["total_canvases"] == 3
    assert found["match_count"] == 1
    assert found["matches"][0]["canvas_id"] == "dgm_tool-gateway-mcp"
    assert found["matches"][0]["file_exists"] is True


def test_export_infra_to_archos_canvas_compose_terraform_and_guards(tmp_path: Path) -> None:
    # 1. Real docker-compose.yml dry-run preview
    preview = export_infra_to_archos_canvas(
        source_path="lab-1-core-engine/docker-compose.yml",
        diagram_id="dgm_lab1-auto",
        title="Lab 1 Auto Export",
    )
    assert preview["dry_run"] is True
    assert preview["source_type"] == "docker_compose"
    assert preview["written_path"] is None
    canvas = preview["canvas_json"]
    assert canvas["schemaVersion"] == 3
    assert canvas["id"] == "dgm_lab1-auto"
    assert canvas["systemBoundaryId"] == "dgm_lab1-auto--boundary"
    # 11 compose services + 1 boundary + 2 external actors (client + sink) = 14 nodes
    assert preview["node_count"] == 14
    assert preview["edge_count"] >= 10

    # 2. Terraform .tf directory parsing + approval-gated write
    tf_dir = tmp_path / "infra"
    tf_dir.mkdir()
    (tf_dir / "main.tf").write_text(
        'resource "aws_vpc" "main" {\n  cidr_block = "10.0.0.0/16"\n}\n'
        'resource "aws_db_instance" "pg" {\n  vpc_id = aws_vpc.main.id\n}\n',
        encoding="utf-8",
    )
    with pytest.raises(PermissionError):
        export_infra_to_archos_canvas(
            source_path="infra",
            diagram_id="dgm_tf-preview",
            dry_run=False,
            confirm_write=False,
            workspace_root=tmp_path,
        )
    with pytest.raises(ValueError):
        export_infra_to_archos_canvas(
            source_path="infra",
            diagram_id="../bad-id",
            workspace_root=tmp_path,
        )
    with pytest.raises(ValueError):
        export_infra_to_archos_canvas(
            source_path="infra",
            diagram_id="dgm_tf-ok",
            dry_run=False,
            confirm_write=True,
            output_path="../../escape.canvas.json",
            workspace_root=tmp_path,
        )

    written = export_infra_to_archos_canvas(
        source_path="infra",
        diagram_id="dgm_tf-ok",
        title="Terraform Export",
        dry_run=False,
        confirm_write=True,
        output_path="out/dgm_tf-ok.canvas.json",
        workspace_root=tmp_path,
    )
    assert written["source_type"] == "terraform"
    assert written["risk_level"] == "local_write_confirmed"
    out_file = tmp_path / "out" / "dgm_tf-ok.canvas.json"
    assert out_file.exists()
    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert loaded["schemaVersion"] == 3
    assert any(
        e["source"].endswith("aws_vpc-main") and e["target"].endswith("aws_db_instance-pg")
        for e in loaded["edges"]
    )
