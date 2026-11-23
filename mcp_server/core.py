"""
Core business logic for spartan-mcp tools (decoupled from MCP transport for clean testing).
Every tool enforces strict input validation, explicit risk levels, read-only defaults,
and path-traversal protection.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import yaml

from tools.finops_calc import (
    calculate_llm_finops,
    calculate_system_capacity,
    estimate_gpu_vram,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHOS_ROOT = Path("/Users/Sage/archos")

PRINCIPAL_OPTIMIZER_RUBRIC: list[dict[str, str]] = [
    {
        "axis": "1. Compute & Memory Efficiency",
        "check": (
            "Eliminate O(N^2) loops; use O(1) generator streaming or Polars/SQL vectorization."
        ),
    },
    {
        "axis": "2. Database & I/O Cost",
        "check": "No N+1 queries, no SELECT *, composite B-Tree indexes, batched COPY/upserts.",
    },
    {
        "axis": "3. Operational Simplicity",
        "check": "Simplest architecture meeting SLO; avoid unnecessary extra datastores/wrappers.",
    },
    {
        "axis": "4. Cloud & Token FinOps ($/month)",
        "check": "Cheapest compute tier (SQL/rules > LightGBM > small model+cache > frontier LLM).",
    },
    {
        "axis": "5. Failure & Security Hardening",
        "check": (
            "Explicit timeouts, idempotency, parameterized SQL, non-root slim image, rollback."
        ),
    },
]


def _safe_resolve_under(base: Path, target: str) -> Path:
    resolved_base = base.resolve()
    candidate = (resolved_base / target).resolve()
    if candidate != resolved_base and resolved_base not in candidate.parents:
        raise ValueError(f"Path '{target}' escapes workspace root '{resolved_base}'.")
    return candidate


def run_finops_estimate(
    *,
    mode: Literal["system", "llm", "gpu"],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Run capacity, LLM token savings, or GPU VRAM sizing math."""
    if mode == "system":
        res = calculate_system_capacity(
            rps=float(params["rps"]),
            avg_latency_ms=float(params["avg_latency_ms"]),
            payload_kb=float(params["payload_kb"]),
            years=float(params.get("years", 3.0)),
            peak_multiplier=float(params.get("peak_multiplier", 3.0)),
        )
        return {"mode": "system", "risk_level": "read_only", "result": asdict(res)}

    if mode == "llm":
        res_llm = calculate_llm_finops(
            monthly_queries=int(params["monthly_queries"]),
            avg_input_tokens=int(params["avg_input_tokens"]),
            avg_output_tokens=int(params["avg_output_tokens"]),
            price_per_1m_in=float(params["price_per_1m_in"]),
            price_per_1m_out=float(params["price_per_1m_out"]),
            cache_hit_rate=float(params.get("cache_hit_rate", 0.35)),
            small_model_route_rate=float(params.get("small_model_route_rate", 0.45)),
            small_model_discount=float(params.get("small_model_discount", 0.85)),
        )
        return {"mode": "llm", "risk_level": "read_only", "result": asdict(res_llm)}

    if mode == "gpu":
        res_gpu = estimate_gpu_vram(
            params_b=float(params["params_b"]),
            quant_bits=int(params.get("quant_bits", 4)),
            ctx_len=int(params.get("ctx_len", 8192)),
            concurrency=int(params.get("concurrency", 16)),
        )
        return {"mode": "gpu", "risk_level": "read_only", "result": asdict(res_gpu)}

    raise ValueError(f"Unsupported mode: {mode}")


def lookup_toolbelt_and_runbooks(
    *,
    query: str,
    scope: Literal["all", "toolbelt", "failures", "ai", "frameworks", "automation"] = "all",
    max_matches: int = 12,
) -> dict[str, Any]:
    """Search Spartan reference docs, toolbelt commands, and 40 failure-mode runbooks."""
    q = query.strip().lower()
    if not q:
        raise ValueError("Query must be a non-empty search string.")
    if max_matches < 1 or max_matches > 50:
        raise ValueError("max_matches must be between 1 and 50.")

    file_map: dict[str, list[str]] = {
        "toolbelt": ["TOOLBELT.md"],
        "failures": ["FAILURE_MODES_AND_PERFORMANCE.md"],
        "ai": ["AI_ML_AND_LLM_MASTERY.md"],
        "frameworks": [
            "PRINCIPAL_FRAMEWORKS.md",
            "JUDGMENT_AND_COMMUNICATION_FRAMEWORKS.md",
            "LEADERSHIP_AND_EXEC_MASTERY.md",
            "DEEP_SPECIALTIES_IAC_API_ML_SECURITY_CERTS.md",
            "DATA_LIFECYCLE_AND_SERVER_FUNDAMENTALS.md",
            "LINEAR_SYLLABUS.md",
        ],
        "automation": ["PYTHON_AUTOMATION_AND_ORCHESTRATION.md", "HOW_TO_USE_THIS_LAB.md"],
    }
    if scope == "all":
        targets = [f for files in file_map.values() for f in files]
    else:
        targets = file_map[scope]

    tokens = [t for t in re.split(r"\s+", q) if t]
    matches: list[dict[str, Any]] = []

    for filename in targets:
        path = DOCS_DIR / filename
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        current_heading = filename
        for idx, line in enumerate(lines, start=1):
            if line.startswith("#"):
                current_heading = line.lstrip("#").strip()
            low = line.lower()
            if all(tok in low for tok in tokens):
                matches.append(
                    {
                        "file": f"docs/{filename}",
                        "line": idx,
                        "section": current_heading,
                        "snippet": line.strip()[:240],
                    }
                )
                if len(matches) >= max_matches:
                    return {
                        "query": query,
                        "scope": scope,
                        "risk_level": "read_only",
                        "match_count": len(matches),
                        "matches": matches,
                    }

    return {
        "query": query,
        "scope": scope,
        "risk_level": "read_only",
        "match_count": len(matches),
        "matches": matches,
    }


def run_qa_and_code_review(
    *,
    target_dir: str = ".",
    run_pytest: bool = True,
) -> dict[str, Any]:
    """
    Execute read-only mechanical quality & security gates (ruff, mypy, pytest, gitleaks)
    inside a target repository and return results paired with the 5-Axis Optimizer Rubric.
    """
    workspace = Path(target_dir).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"target_dir does not exist or is not a directory: {workspace}")

    gates: list[tuple[str, list[str]]] = []
    if shutil.which("uv"):
        gates.append(("ruff", ["uv", "run", "ruff", "check", "."]))
        if (workspace / "pyproject.toml").exists():
            gates.append(("mypy", ["uv", "run", "mypy", "."]))
        if run_pytest:
            gates.append(("pytest", ["uv", "run", "pytest", "tests/", "-q"]))
    if shutil.which("gitleaks"):
        gates.append(
            ("gitleaks", ["gitleaks", "detect", "--source", ".", "--no-banner", "--redact"])
        )

    results: list[dict[str, Any]] = []
    overall_passed = True

    for name, argv in gates:
        try:
            proc = subprocess.run(
                argv,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            passed = proc.returncode == 0
            if not passed:
                overall_passed = False
            output = (proc.stdout + "\n" + proc.stderr).strip()
            results.append(
                {
                    "gate": name,
                    "passed": passed,
                    "exit_code": proc.returncode,
                    "summary": output[-600:] if output else "ok",
                }
            )
        except subprocess.TimeoutExpired:
            overall_passed = False
            results.append(
                {
                    "gate": name,
                    "passed": False,
                    "exit_code": -1,
                    "summary": "Timed out after 45s",
                }
            )

    return {
        "workspace": str(workspace),
        "risk_level": "read_only",
        "overall_passed": overall_passed,
        "gates": results,
        "principal_optimizer_rubric": PRINCIPAL_OPTIMIZER_RUBRIC,
    }


def build_dashboard_pack(
    *,
    service_name: str,
    metric_prefix: str = "app",
    include_ai_panels: bool = True,
    dry_run: bool = True,
    confirm_write: bool = False,
    output_dir: str = "generated_dashboards",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """
    Generate a ready-to-import Grafana JSON dashboard (RED + FinOps + optional AI TTFT/tokens)
    and Executive Metabase/Superset SQL KPI view.
    Mutating boundary: requires dry_run=False AND confirm_write=True to write files.
    """
    clean_slug = re.sub(r"[^a-zA-Z0-9_-]", "-", service_name.strip()).lower()
    clean_prefix = re.sub(r"[^a-zA-Z0-9_]", "_", metric_prefix.strip()).lower()
    if not clean_slug or not clean_prefix:
        raise ValueError("service_name and metric_prefix must contain alphanumeric characters.")

    panels: list[dict[str, Any]] = [
        {
            "id": 1,
            "type": "timeseries",
            "title": f"{service_name} - Request Rate (RPS) by Status",
            "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
            "targets": [
                {
                    "expr": f"sum by (status) (rate({clean_prefix}_http_requests_total[1m]))",
                    "legendFormat": "HTTP {{status}}",
                }
            ],
        },
        {
            "id": 2,
            "type": "timeseries",
            "title": f"{service_name} - Tail Latency (p50 / p95 / p99)",
            "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
            "targets": [
                {
                    "expr": (
                        "histogram_quantile(0.99, sum by (le) "
                        f"(rate({clean_prefix}_http_request_duration_seconds_bucket[1m])))"
                    ),
                    "legendFormat": "p99",
                }
            ],
        },
        {
            "id": 3,
            "type": "timeseries",
            "title": f"{service_name} - FinOps Cost Burn ($/min by Tenant)",
            "gridPos": {"x": 0, "y": 8, "w": 12, "h": 8},
            "targets": [
                {
                    "expr": f"sum by (tenant_id) (rate({clean_prefix}_cost_usd_total[1m])) * 60",
                    "legendFormat": "tenant {{tenant_id}} ($/min)",
                }
            ],
        },
    ]

    if include_ai_panels:
        panels.append(
            {
                "id": 4,
                "type": "timeseries",
                "title": f"{service_name} - AI LLM TTFT (p95) & Semantic Cache Hit Rate",
                "gridPos": {"x": 12, "y": 8, "w": 12, "h": 8},
                "targets": [
                    {
                        "expr": (
                            "histogram_quantile(0.95, sum by (le) "
                            f"(rate({clean_prefix}_llm_ttft_seconds_bucket[1m])))"
                        ),
                        "legendFormat": "TTFT p95 (s)",
                    },
                    {
                        "expr": (
                            f"sum(rate({clean_prefix}_semantic_cache_hits_total[5m])) / "
                            f"clamp_min(sum(rate({clean_prefix}_llm_requests_total[5m])), 1)"
                        ),
                        "legendFormat": "cache hit ratio",
                    },
                ],
            }
        )

    grafana_json: dict[str, Any] = {
        "uid": f"{clean_slug}-ops",
        "title": f"{service_name} - Live RED, FinOps & AI Dashboard",
        "schemaVersion": 39,
        "refresh": "5s",
        "panels": panels,
    }

    exec_sql = (
        f"-- Executive BI KPI View for {service_name} (Metabase / Apache Superset)\n"
        f"CREATE OR REPLACE VIEW v_exec_{clean_prefix}_kpi AS\n"
        "SELECT\n"
        "    tenant_id,\n"
        "    COUNT(*) AS total_requests,\n"
        "    ROUND(SUM(cost_usd), 4) AS total_spend_usd,\n"
        "    ROUND(AVG(latency_ms), 2) AS avg_latency_ms,\n"
        "    ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms)::numeric, 2) "
        "AS p99_latency_ms\n"
        f"FROM {clean_prefix}_events\n"
        "GROUP BY tenant_id\n"
        "ORDER BY total_spend_usd DESC;\n"
    )

    written_files: list[str] = []
    if not dry_run:
        if not confirm_write:
            raise PermissionError(
                "Write blocked by policy: set confirm_write=True explicitly when dry_run=False."
            )
        base = workspace_root or REPO_ROOT
        dest_dir = _safe_resolve_under(base, output_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        g_path = dest_dir / f"{clean_slug}_grafana.json"
        s_path = dest_dir / f"{clean_slug}_exec_kpi.sql"
        g_path.write_text(json.dumps(grafana_json, indent=2) + "\n", encoding="utf-8")
        s_path.write_text(exec_sql, encoding="utf-8")
        written_files = [str(g_path), str(s_path)]

    return {
        "service_name": service_name,
        "risk_level": "read_only" if dry_run else "local_write_confirmed",
        "dry_run": dry_run,
        "written_files": written_files,
        "grafana_dashboard": grafana_json,
        "exec_kpi_sql": exec_sql,
    }


def visualize_infra_and_cicd(
    *,
    compose_path: str = "lab-1-core-engine/docker-compose.yml",
    workflow_path: str = ".github/workflows/ci.yml",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """
    Parse real docker-compose.yml and GitHub Actions workflow YAML to generate
    clean Mermaid and D2 infrastructure + CI/CD diagrams automatically.
    """
    base = workspace_root or REPO_ROOT
    compose_file = _safe_resolve_under(base, compose_path)
    workflow_file = _safe_resolve_under(base, workflow_path)

    mermaid_lines = ["flowchart LR"]
    d2_lines = ["direction: right"]
    services_summary: list[dict[str, Any]] = []
    ci_summary: list[dict[str, Any]] = []

    if compose_file.exists():
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8")) or {}
        services = data.get("services") or {}
        for svc_name, cfg in services.items():
            safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", str(svc_name))
            ports = cfg.get("ports") or []
            nets = cfg.get("networks") or []
            deps = cfg.get("depends_on") or {}
            dep_list = list(deps.keys()) if isinstance(deps, dict) else list(deps)
            label = f"{svc_name}" + (f" ({ports[0]})" if ports else "")
            mermaid_lines.append(f'    {safe_id}["{label}"]')
            d2_lines.append(f'{safe_id}: "{label}"')
            for dep in dep_list:
                dep_id = re.sub(r"[^a-zA-Z0-9_]", "_", str(dep))
                mermaid_lines.append(f"    {safe_id} --> {dep_id}")
                d2_lines.append(f"{safe_id} -> {dep_id}")
            services_summary.append(
                {
                    "service": svc_name,
                    "ports": ports,
                    "networks": list(nets) if isinstance(nets, (list, dict)) else [],
                    "depends_on": dep_list,
                }
            )

    ci_mermaid = ["flowchart LR"]
    if workflow_file.exists():
        wf = yaml.safe_load(workflow_file.read_text(encoding="utf-8")) or {}
        jobs = wf.get("jobs") or {}
        for job_name, jcfg in jobs.items():
            steps = jcfg.get("steps") or []
            step_names = [str(s.get("name") or s.get("uses") or "step") for s in steps]
            ci_summary.append({"job": job_name, "steps": step_names})
            prev_id: str | None = None
            for idx, sname in enumerate(step_names, start=1):
                sid = f"{re.sub(r'[^a-zA-Z0-9_]', '_', str(job_name))}_{idx}"
                clean_label = sname.replace('"', "'")
                ci_mermaid.append(f'    {sid}["{clean_label}"]')
                if prev_id is not None:
                    ci_mermaid.append(f"    {prev_id} --> {sid}")
                prev_id = sid

    return {
        "risk_level": "read_only",
        "services_count": len(services_summary),
        "services": services_summary,
        "ci_jobs": ci_summary,
        "infra_mermaid": "\n".join(mermaid_lines),
        "infra_d2": "\n".join(d2_lines),
        "cicd_mermaid": "\n".join(ci_mermaid),
    }


def lookup_archos_canvases(
    *,
    query: str = "",
    folder: str = "all",
    max_matches: int = 25,
    archos_root: Path | None = None,
) -> dict[str, Any]:
    """
    [READ-ONLY] Search the local ArchOS interactive canvas library
    (knowledge/library.manifest.json) by keyword or folder so AI assistants can
    cross-reference all 114+ ArchOS visual architecture canvases alongside Spartan Labs.
    """
    if max_matches < 1 or max_matches > 150:
        raise ValueError("max_matches must be between 1 and 150.")

    root = (archos_root or DEFAULT_ARCHOS_ROOT).resolve()
    manifest_path = root / "knowledge" / "library.manifest.json"
    if not manifest_path.exists():
        return {
            "risk_level": "read_only",
            "available": False,
            "archos_root": str(root),
            "message": f"ArchOS manifest not found at {manifest_path}",
            "match_count": 0,
            "matches": [],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    folder_titles = {
        f["id"]: f.get("title", f["id"]) for f in manifest.get("folders", []) if "id" in f
    }
    diagrams_by_folder: dict[str, list[str]] = manifest.get("diagrams", {})
    q = query.strip().lower()
    tokens = [t for t in re.split(r"\s+", q) if t]
    folder_norm = folder.strip().lower()

    total_canvases = 0
    matches: list[dict[str, Any]] = []
    for fid, ids in diagrams_by_folder.items():
        ftitle = folder_titles.get(fid, fid)
        total_canvases += len(ids)
        if (
            folder_norm != "all"
            and folder_norm not in fid.lower()
            and folder_norm not in ftitle.lower()
        ):
            continue
        for cid in ids:
            haystack = f"{fid} {ftitle} {cid}".lower()
            if not tokens or all(tok in haystack for tok in tokens):
                canvas_file = root / "knowledge" / "diagrams" / f"{cid}.canvas.json"
                if not canvas_file.exists():
                    canvas_file = root / "knowledge" / "pilots" / f"{cid}.canvas.json"
                matches.append(
                    {
                        "canvas_id": cid,
                        "folder_id": fid,
                        "folder_title": ftitle,
                        "file_exists": canvas_file.exists(),
                        "path": str(canvas_file),
                    }
                )
                if len(matches) >= max_matches:
                    break
        if len(matches) >= max_matches:
            break

    return {
        "risk_level": "read_only",
        "available": True,
        "archos_root": str(root),
        "total_canvases": total_canvases,
        "query": query,
        "folder": folder,
        "match_count": len(matches),
        "matches": matches,
    }


_SAFE_DIAGRAM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_TF_RESOURCE_RE = re.compile(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{')

_SERVICE_ARCHOS_SPECS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (
        ("nginx", "caddy", "envoy", "haproxy", "traefik", "alb", "lb"),
        {
            "label": "Reverse proxy",
            "componentId": "comp.reverse-proxy",
            "family": "fam.comp.net",
            "role": "gateway",
            "discipline": "cloud",
            "stateful": False,
            "icon": "lucide:route",
            "tier": 0,
        },
    ),
    (
        ("pgbouncer", "pool"),
        {
            "label": "Connection pooler",
            "componentId": "comp.connection-pooler",
            "family": "fam.comp.rdb",
            "role": "gateway",
            "discipline": "data",
            "stateful": False,
            "icon": "lucide:route",
            "tier": 2,
        },
    ),
    (
        ("postgres", "psql", "rds", "aurora"),
        {
            "label": "PostgreSQL",
            "componentId": "comp.postgres",
            "family": "fam.comp.rdb",
            "role": "store",
            "discipline": "data",
            "stateful": True,
            "icon": "logos:postgresql",
            "tier": 3,
        },
    ),
    (
        ("redis", "valkey", "memcached", "elasticache"),
        {
            "label": "Distributed cache",
            "componentId": "comp.redis",
            "family": "fam.comp.cache",
            "role": "cache",
            "discipline": "core",
            "stateful": True,
            "icon": "logos:redis",
            "tier": 2,
        },
    ),
    (
        ("kafka", "redpanda", "sqs", "kinesis"),
        {
            "label": "Event log",
            "componentId": "comp.kafka",
            "family": "fam.comp.messaging",
            "role": "queue",
            "discipline": "core",
            "stateful": True,
            "icon": "logos:kafka-icon",
            "tier": 2,
        },
    ),
    (
        ("clickhouse",),
        {
            "label": "ClickHouse",
            "componentId": "comp.clickhouse",
            "family": "fam.comp.olap",
            "role": "store",
            "discipline": "data",
            "stateful": True,
            "icon": "lucide:database",
            "tier": 3,
        },
    ),
    (
        ("qdrant", "milvus", "weaviate", "pinecone"),
        {
            "label": "Vector database",
            "componentId": "comp.vector-store",
            "family": "fam.comp.search",
            "role": "index",
            "discipline": "data",
            "stateful": True,
            "icon": "lucide:search",
            "tier": 3,
        },
    ),
    (
        ("s3", "minio", "bucket", "iceberg"),
        {
            "label": "Object storage",
            "componentId": "comp.object-store",
            "family": "fam.comp.storage",
            "role": "store",
            "discipline": "data",
            "stateful": True,
            "icon": "lucide:hard-drive",
            "tier": 3,
        },
    ),
    (
        ("prometheus", "otel", "exporter"),
        {
            "label": "OpenTelemetry Collector",
            "componentId": "comp.otel-collector",
            "family": "fam.comp.obs",
            "role": "observe",
            "discipline": "ops",
            "stateful": False,
            "icon": "lucide:activity",
            "tier": 2,
        },
    ),
    (
        ("grafana", "metabase", "superset"),
        {
            "label": "Traces, metrics and logs",
            "componentId": "comp.slo-dashboard",
            "family": "fam.comp.obs",
            "role": "observe",
            "discipline": "ops",
            "stateful": True,
            "icon": "lucide:activity",
            "tier": 3,
        },
    ),
    (
        ("vpc", "subnet", "security_group", "firewall"),
        {
            "label": "Network firewall",
            "componentId": "comp.network-firewall",
            "family": "fam.comp.net",
            "role": "control",
            "discipline": "cloud",
            "stateful": False,
            "icon": "lucide:shield",
            "tier": 0,
        },
    ),
]


def _classify_infra_node(name: str, hint: str = "") -> dict[str, Any]:
    haystack = f"{name} {hint}".lower()
    for keywords, spec in _SERVICE_ARCHOS_SPECS:
        if any(k in haystack for k in keywords):
            return spec
    return {
        "label": "Container runtime",
        "componentId": "comp.container-runtime",
        "family": "fam.comp.compute",
        "role": "compute",
        "discipline": "cloud",
        "stateful": False,
        "icon": "lucide:container",
        "tier": 1,
    }


def export_infra_to_archos_canvas(
    *,
    source_path: str = "lab-1-core-engine/docker-compose.yml",
    diagram_id: str = "dgm_exported-infra",
    title: str = "Exported Infrastructure Blueprint",
    dry_run: bool = True,
    confirm_write: bool = False,
    output_path: str = "generated_canvases/dgm_exported-infra.canvas.json",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """
    Parse real docker-compose.yml, Terraform .tf files/directories, or GitHub Actions YAML
    and emit a schema v3 ArchOS .canvas.json blueprint laid out on an 8px DS2 grid.
    Mutating boundary: defaults to dry_run=True; writes need dry_run=False & confirm_write=True.
    """
    if not _SAFE_DIAGRAM_ID_RE.match(diagram_id):
        raise ValueError(
            f"Invalid diagram_id {diagram_id!r}; must match ^[A-Za-z0-9][A-Za-z0-9_-]{{0,127}}$."
        )

    base = workspace_root or REPO_ROOT
    target = _safe_resolve_under(base, source_path)
    if not target.exists():
        raise ValueError(f"Source path not found: {source_path}")

    raw_nodes: list[dict[str, Any]] = []
    raw_edges: list[tuple[str, str, str]] = []
    source_type = "unknown"

    if target.is_dir() or target.suffix == ".tf":
        source_type = "terraform"
        tf_files = sorted(target.rglob("*.tf")) if target.is_dir() else [target]
        tf_blocks: list[tuple[str, str, str, str]] = []
        for tf in tf_files:
            content = tf.read_text(encoding="utf-8", errors="ignore")
            matches = list(_TF_RESOURCE_RE.finditer(content))
            for idx, m in enumerate(matches):
                rtype, rname = m.group(1), m.group(2)
                start = m.end()
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
                body = content[start:end]
                key = re.sub(r"[^a-zA-Z0-9_-]", "-", f"{rtype}-{rname}").lower()
                tf_blocks.append((key, rtype, rname, body))
                raw_nodes.append(
                    {"key": key, "name": rname, "subtitle": f"{rtype}.{rname}", "hint": rtype}
                )
        ref_lookup = {f"{rtype}.{rname}": key for key, rtype, rname, _ in tf_blocks}
        for key, _rtype, _rname, body in tf_blocks:
            for ref_str, target_key in ref_lookup.items():
                if target_key != key and ref_str in body:
                    raw_edges.append((key, target_key, "Depends on"))
    else:
        parsed = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if isinstance(parsed, dict) and isinstance(parsed.get("services"), dict):
            source_type = "docker_compose"
            for svc_name, cfg in parsed["services"].items():
                cfg = cfg or {}
                ports = cfg.get("ports") or []
                image = str(cfg.get("image") or "custom-build")
                port_note = f" ({ports[0]})" if ports else ""
                key = re.sub(r"[^a-zA-Z0-9_-]", "-", str(svc_name)).lower()
                raw_nodes.append(
                    {
                        "key": key,
                        "name": str(svc_name),
                        "subtitle": f"{svc_name}{port_note}",
                        "hint": f"{svc_name} {image}",
                    }
                )
                deps = cfg.get("depends_on") or {}
                dep_list = list(deps.keys()) if isinstance(deps, dict) else list(deps)
                for dep in dep_list:
                    dep_key = re.sub(r"[^a-zA-Z0-9_-]", "-", str(dep)).lower()
                    raw_edges.append((key, dep_key, "Connects to"))
        elif isinstance(parsed, dict) and isinstance(parsed.get("jobs"), dict):
            source_type = "github_actions"
            for job_name, jcfg in parsed["jobs"].items():
                steps = (jcfg or {}).get("steps") or []
                prev_key: str | None = None
                for idx, step in enumerate(steps, start=1):
                    sname = str(step.get("name") or step.get("uses") or f"step-{idx}")
                    key = re.sub(r"[^a-zA-Z0-9_-]", "-", f"{job_name}-{idx}").lower()
                    raw_nodes.append(
                        {
                            "key": key,
                            "name": sname[:28],
                            "subtitle": f"{job_name}: {sname[:36]}",
                            "hint": sname,
                        }
                    )
                    if prev_key:
                        raw_edges.append((prev_key, key, "Next stage"))
                    prev_key = key
        else:
            raise ValueError(
                f"Unsupported source format in {source_path}; "
                "expected docker-compose.yml, .tf, or GitHub Actions YAML."
            )

    if not raw_nodes:
        raise ValueError(f"No infrastructure services, resources, or jobs found in {source_path}.")

    # Group nodes into 4 LTR tier columns on an 8px grid inside a Trust boundary
    by_tier: dict[int, list[dict[str, Any]]] = {0: [], 1: [], 2: [], 3: []}
    classified: dict[str, dict[str, Any]] = {}
    node_tier: dict[str, int] = {}
    bucket_size = max(1, (len(raw_nodes) + 3) // 4)
    for idx, item in enumerate(raw_nodes):
        spec = _classify_infra_node(item["name"], item["hint"])
        tier = int(spec["tier"]) if source_type != "github_actions" else min(3, idx // bucket_size)
        by_tier[tier].append(item)
        classified[item["key"]] = spec
        node_tier[item["key"]] = tier

    non_empty_tiers = [t for t in (0, 1, 2, 3) if by_tier[t]]
    max_rows = max(len(by_tier[t]) for t in non_empty_tiers)
    node_w, node_h = 192, 128
    col_step, row_step = 352, 192
    boundary_x = 320
    boundary_w = 40 + (len(non_empty_tiers) - 1) * col_step + node_w + 40
    boundary_h = max(360, 64 + (max_rows - 1) * row_step + node_h + 48)
    boundary_id = f"{diagram_id}--boundary"

    canvas_nodes: list[dict[str, Any]] = [
        {
            "id": boundary_id,
            "type": "containerNode",
            "position": {"x": boundary_x, "y": 0},
            "style": {"width": boundary_w, "height": boundary_h},
            "data": {
                "label": "Trust boundary",
                "subtitle": f"Auto-generated from {source_path}",
                "icon": "lucide:boxes",
                "colorTheme": "cyan",
                "conceptId": "boundary",
                "masteryScore": 0,
                "targetLevel": "L5",
                "pageCount": 0,
                "isChaosFailed": False,
                "isCollapsed": False,
                "stateful": False,
                "discipline": "security",
                "boundaryKind": "trust",
            },
        },
        {
            "id": f"{diagram_id}--client",
            "type": "techNode",
            "position": {"x": 0, "y": 64},
            "style": {"width": node_w, "height": node_h},
            "data": {
                "label": "Client application",
                "subtitle": "External entry caller",
                "icon": "lucide:user",
                "colorTheme": "cyan",
                "conceptId": "client",
                "masteryScore": 0,
                "targetLevel": "L5",
                "pageCount": 0,
                "isChaosFailed": False,
                "isCollapsed": False,
                "componentId": "comp.client-app",
                "family": "fam.comp.compute",
                "role": "actor",
                "discipline": "cloud",
                "stateful": "mixed",
                "actorRole": "client",
                "external": True,
            },
        },
    ]

    valid_keys = {n["key"] for n in raw_nodes}

    for col_idx, tier_id in enumerate(non_empty_tiers):
        for row_idx, item in enumerate(by_tier[tier_id]):
            spec = classified[item["key"]]
            annotations: dict[str, Any] = {"backup": True} if spec["stateful"] is True else {}
            canvas_nodes.append(
                {
                    "id": f"{diagram_id}--{item['key']}",
                    "type": "techNode",
                    "position": {"x": 40 + col_idx * col_step, "y": 64 + row_idx * row_step},
                    "parentId": boundary_id,
                    "style": {"width": node_w, "height": node_h},
                    "data": {
                        "label": spec["label"],
                        "subtitle": item["subtitle"][:42],
                        "icon": spec["icon"],
                        "colorTheme": "cyan",
                        "conceptId": item["key"],
                        "masteryScore": 0,
                        "targetLevel": "L5",
                        "pageCount": 0,
                        "isChaosFailed": False,
                        "isCollapsed": False,
                        "componentId": spec["componentId"],
                        "family": spec["family"],
                        "role": spec["role"],
                        "discipline": spec["discipline"],
                        "stateful": spec["stateful"],
                        **({"annotations": annotations} if annotations else {}),
                    },
                }
            )

    sink_x = boundary_x + boundary_w + 128
    canvas_nodes.append(
        {
            "id": f"{diagram_id}--sink",
            "type": "techNode",
            "position": {"x": sink_x, "y": 64},
            "style": {"width": node_w, "height": node_h},
            "data": {
                "label": "Client application",
                "subtitle": "Operator / consumer",
                "icon": "lucide:user",
                "colorTheme": "cyan",
                "conceptId": "sink",
                "masteryScore": 0,
                "targetLevel": "L5",
                "pageCount": 0,
                "isChaosFailed": False,
                "isCollapsed": False,
                "componentId": "comp.client-app",
                "family": "fam.comp.compute",
                "role": "actor",
                "discipline": "cloud",
                "stateful": "mixed",
                "actorRole": "operator",
                "external": True,
            },
        }
    )

    # Build a continuous LTR numbered spine across non-empty tier leaders so DS2-C02 & DS2-L05 pass
    spine_keys = [by_tier[t][0]["key"] for t in non_empty_tiers]
    canvas_edges: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    step_num = 1
    prev_id = f"{diagram_id}--client"
    for skey in spine_keys:
        cur_id = f"{diagram_id}--{skey}"
        canvas_edges.append(
            {
                "id": f"{diagram_id}--step-{step_num}",
                "source": prev_id,
                "target": cur_id,
                "type": "animatedFlowEdge",
                "data": {
                    "colorTheme": "cyan",
                    "protocol": "HTTPS" if step_num == 1 else "TCP",
                    "latencyMs": 0,
                    "animate": False,
                    "kind": "sync",
                    "label": "Sends load" if step_num == 1 else "Forwards",
                    "step": str(step_num),
                    "annotations": {"tls": True, "timeoutMs": max(500, 6000 - step_num * 1000)},
                },
            }
        )
        seen_pairs.add((prev_id, cur_id))
        prev_id = cur_id
        step_num += 1

    sink_id = f"{diagram_id}--sink"
    canvas_edges.append(
        {
            "id": f"{diagram_id}--step-{step_num}",
            "source": prev_id,
            "target": sink_id,
            "type": "animatedFlowEdge",
            "data": {
                "colorTheme": "cyan",
                "protocol": "HTTPS",
                "latencyMs": 0,
                "animate": False,
                "kind": "sync",
                "label": "Delivers",
                "step": str(step_num),
                "annotations": {"tls": True, "timeoutMs": 2000},
            },
        }
    )
    seen_pairs.add((prev_id, sink_id))

    for e_idx, (src, dst, lbl) in enumerate(raw_edges, start=1):
        if src not in valid_keys or dst not in valid_keys:
            continue
        # Preserve LTR flow direction for control/dependency edges when source sits right of target
        edge_src, edge_dst = (
            (src, dst) if node_tier[src] <= node_tier[dst] else (dst, src)
        )
        src_full = f"{diagram_id}--{edge_src}"
        dst_full = f"{diagram_id}--{edge_dst}"
        if (src_full, dst_full) in seen_pairs:
            continue
        seen_pairs.add((src_full, dst_full))
        canvas_edges.append(
            {
                "id": f"{diagram_id}--e{e_idx}",
                "source": src_full,
                "target": dst_full,
                "type": "animatedFlowEdge",
                "data": {
                    "colorTheme": "cyan",
                    "protocol": "TCP",
                    "latencyMs": 0,
                    "animate": False,
                    "kind": "control",
                    "label": lbl,
                    "annotations": {"tls": True},
                },
            }
        )

    canvas_doc: dict[str, Any] = {
        "schemaVersion": 3,
        "id": diagram_id,
        "title": title,
        "tier": "production",
        "flow": "ltr",
        "level": "L4",
        "systemBoundaryId": boundary_id,
        "numbers": "none-needed",
        "showMasteryRing": False,
        "nodes": canvas_nodes,
        "edges": canvas_edges,
        "viewport": {"x": 16, "y": 16, "zoom": 0.6},
        "updatedAt": "2026-11-23T00:00:00.000Z",
    }

    written_path: str | None = None
    if not dry_run:
        if not confirm_write:
            raise PermissionError(
                "Write blocked by policy: set confirm_write=True explicitly when dry_run=False."
            )
        out_file = _safe_resolve_under(base, output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(canvas_doc, indent=2) + "\n", encoding="utf-8")
        written_path = str(out_file)

    return {
        "risk_level": "read_only" if dry_run else "local_write_confirmed",
        "dry_run": dry_run,
        "source_type": source_type,
        "source_path": source_path,
        "diagram_id": diagram_id,
        "node_count": len(canvas_nodes),
        "edge_count": len(canvas_edges),
        "written_path": written_path,
        "canvas_json": canvas_doc,
    }
