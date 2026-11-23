"""
spartan-mcp: Personal Principal Engineer MCP Server.

Run via stdio (for Claude Code, Cursor, Antigravity, or any MCP client):
  uv run python -m mcp_server.server
"""
from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer

from mcp_server.core import (
    build_dashboard_pack,
    export_infra_to_archos_canvas,
    lookup_archos_canvases,
    lookup_toolbelt_and_runbooks,
    run_finops_estimate,
    run_qa_and_code_review,
)
from mcp_server.core import (
    visualize_infra_and_cicd as build_infra_and_cicd_diagrams,
)

mcp = MCPServer(
    name="spartan-mcp",
    title="Spartan Personal Principal Engineer MCP Server",
    description=(
        "Portable Principal Engineer toolbelt: FinOps & GPU sizing, 440-unit Tool Belt & "
        "40 Failure-Mode runbook lookup, automated QA reviewer, approval-gated Grafana/BI "
        "dashboard pack generator, and IaC/CI-CD diagram visualizer."
    ),
    version="0.1.0",
)


@mcp.tool()
def finops_estimate(
    mode: Literal["system", "llm", "gpu"],
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    [READ-ONLY | scope: local:compute] Run Principal capacity, LLM FinOps, or GPU VRAM math.
    - mode='system': params={rps, avg_latency_ms, payload_kb, years?, peak_multiplier?}
    - mode='llm': params={monthly_queries, avg_input_tokens, avg_output_tokens,
      price_per_1m_in, price_per_1m_out, cache_hit_rate?, small_model_route_rate?,
      small_model_discount?}
    - mode='gpu': params={params_b, quant_bits?, ctx_len?, concurrency?}
    """
    return run_finops_estimate(mode=mode, params=params)


@mcp.tool()
def toolbelt_and_runbook_lookup(
    query: str,
    scope: Literal["all", "toolbelt", "failures", "ai", "frameworks", "automation"] = "all",
    max_matches: int = 12,
) -> dict[str, Any]:
    """
    [READ-ONLY | scope: repo:docs:read] Search your personal Spartan Tool Belt
    (Backend, Data, AI/ML, Infra, Security, React/React Native), 440 units,
    and 40 Failure Mode triage runbooks.
    """
    return lookup_toolbelt_and_runbooks(query=query, scope=scope, max_matches=max_matches)


@mcp.tool()
def qa_and_code_review(
    target_dir: str = ".",
    run_pytest: bool = True,
) -> dict[str, Any]:
    """
    [READ-ONLY | scope: repo:read+linters] Run mechanical quality & security gates
    (ruff, mypy, pytest, gitleaks) on a workspace and return pass/fail results
    plus the 5-Axis Principal Optimizer & Cost Review Rubric.
    """
    return run_qa_and_code_review(target_dir=target_dir, run_pytest=run_pytest)


@mcp.tool()
def generate_dashboard_pack(
    service_name: str,
    metric_prefix: str = "app",
    include_ai_panels: bool = True,
    dry_run: bool = True,
    confirm_write: bool = False,
    output_dir: str = "generated_dashboards",
) -> dict[str, Any]:
    """
    [APPROVAL-GATED WRITE | scope: repo:write:dashboards] Generate a ready-to-import
    Grafana JSON dashboard (RED + FinOps + optional AI TTFT/cache) and Executive BI SQL view.
    Defaults to dry_run=True (safe preview). To write files, pass BOTH dry_run=False
    AND confirm_write=True.
    """
    return build_dashboard_pack(
        service_name=service_name,
        metric_prefix=metric_prefix,
        include_ai_panels=include_ai_panels,
        dry_run=dry_run,
        confirm_write=confirm_write,
        output_dir=output_dir,
    )


@mcp.tool()
def visualize_infra_and_cicd(
    compose_path: str = "lab-1-core-engine/docker-compose.yml",
    workflow_path: str = ".github/workflows/ci.yml",
) -> dict[str, Any]:
    """
    [READ-ONLY | scope: repo:read] Parse real docker-compose.yml and GitHub Actions
    workflow YAML to auto-generate Mermaid and D2 infrastructure + CI/CD diagrams.
    """
    return build_infra_and_cicd_diagrams(
        compose_path=compose_path,
        workflow_path=workflow_path,
    )


@mcp.tool()
def archos_canvas_lookup(
    query: str = "",
    folder: str = "all",
    max_matches: int = 25,
) -> dict[str, Any]:
    """
    [READ-ONLY | scope: local:archos:read] Search your 120+ local ArchOS interactive
    architecture canvases by keyword or folder (spartan-labs, foundations, data-lifecycle,
    classic-systems, ai-agents, pilots) to pair visual whiteboards with Spartan Labs.
    """
    return lookup_archos_canvases(query=query, folder=folder, max_matches=max_matches)


@mcp.tool()
def infra_to_archos_canvas(
    source_path: str = "lab-1-core-engine/docker-compose.yml",
    diagram_id: str = "dgm_exported-infra",
    title: str = "Exported Infrastructure Blueprint",
    dry_run: bool = True,
    confirm_write: bool = False,
    output_path: str = "generated_canvases/dgm_exported-infra.canvas.json",
) -> dict[str, Any]:
    """
    [APPROVAL-GATED WRITE | scope: repo:write:canvases] Parse real docker-compose.yml,
    Terraform .tf files/directories, or GitHub Actions CI YAML and generate a schema v3
    ArchOS .canvas.json blueprint ready to load into ArchOS. Defaults to dry_run=True
    (safe preview). To write to disk, pass BOTH dry_run=False AND confirm_write=True.
    """
    return export_infra_to_archos_canvas(
        source_path=source_path,
        diagram_id=diagram_id,
        title=title,
        dry_run=dry_run,
        confirm_write=confirm_write,
        output_path=output_path,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
