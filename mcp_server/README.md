# `spartan-mcp` — Personal Principal Engineer MCP Server

Your portable "handyman toolbelt" MCP server. Plug it into **Claude Code, Cursor, Antigravity, or any MCP-compatible AI client** so every AI session inherits your exact Tool Belt (Backend, Data, AI/ML, Infra, Security, React/React Native), your 40 Failure-Mode Runbooks, your FinOps calculators, your 6-gate QA reviewer, and instant Grafana/BI dashboard + IaC/CI-CD generators.

---

## Tool Catalog (Contract, Risk & Approval Boundaries)

| Tool Name | Risk Level | Permission Scope | What It Does | Failure Modes |
| :--- | :--- | :--- | :--- | :--- |
| **`finops_estimate`** | `read_only` | `local:compute` | Little's Law capacity, LLM semantic-cache/routing `$/yr` savings, and GPU VRAM/KV-cache sizing. | `ValueError` on negative numbers, rates outside `[0,1]`, or unknown mode. |
| **`toolbelt_and_runbook_lookup`** | `read_only` | `repo:docs:read` | Searches `docs/TOOLBELT.md`, `FAILURE_MODES_AND_PERFORMANCE.md`, `AI_ML_AND_LLM_MASTERY.md`, and all Principal frameworks. | `ValueError` on empty query or `max_matches` outside `1..50`. |
| **`qa_and_code_review`** | `read_only` | `repo:read+linters` | Runs `ruff`, `mypy`, `pytest`, and `gitleaks` safely via explicit argv lists (45s timeout) + returns the 5-Axis Principal Optimizer Rubric. | `ValueError` on missing directory; gate failures returned cleanly with exit code & stderr snippet. |
| **`generate_dashboard_pack`** | `local_write_guarded` | `repo:write:dashboards` | Generates Grafana JSON (RED + FinOps + AI TTFT/cache) + Executive SQL KPI view. **Defaults to `dry_run=True`**. | `PermissionError` if `dry_run=False` without explicit `confirm_write=True`; `ValueError` on path traversal (`..`). |
| **`visualize_infra_and_cicd`** | `read_only` | `repo:read` | Parses `docker-compose.yml` and `.github/workflows/*.yml` into Mermaid & D2 diagrams. | `ValueError` on path traversal outside workspace. |

---

## Quick Start & Client Configuration

### Run Locally (stdio transport)
```bash
cd /Users/Sage/code/spartan-systems-lab
make mcp
```

### Plug Into Claude Code / Cursor / Antigravity (`mcpServers` JSON)
```json
{
  "mcpServers": {
    "spartan-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/Sage/code/spartan-systems-lab",
        "run",
        "python",
        "-m",
        "mcp_server.server"
      ]
    }
  }
}
```
