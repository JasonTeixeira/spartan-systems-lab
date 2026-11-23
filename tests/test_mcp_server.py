import asyncio
from pathlib import Path

import pytest

from mcp_server.core import (
    build_dashboard_pack,
    lookup_toolbelt_and_runbooks,
    run_finops_estimate,
    visualize_infra_and_cicd,
)
from mcp_server.server import mcp


def test_mcp_server_registers_all_5_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    expected = {
        "finops_estimate",
        "toolbelt_and_runbook_lookup",
        "qa_and_code_review",
        "generate_dashboard_pack",
        "visualize_infra_and_cicd",
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
