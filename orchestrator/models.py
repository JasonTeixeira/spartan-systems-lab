"""Strict Pydantic v2 models & per-tier resource quotas for multi-tenant sandboxes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

LabTemplateId = Literal[
    "lab0-free-range",
    "lab1-core-engine",
    "lab2-linux-tls",
    "lab3-lakehouse-wap",
    "lab4-rag-acl",
    "lab5-raft-internals",
    "lab6-k8s-ebpf",
    "lab7-linux-sre",
    "lab8-scale-api",
    "lab9-iac-iam",
    "lab10-ai-gpu-mcp",
    "lab11-p0-capstone",
]

SandboxTier = Literal["free", "pro", "enterprise"]
SandboxStatus = Literal["provisioning", "running", "terminated", "expired"]


@dataclass(frozen=True)
class TierQuota:
    tier: SandboxTier
    max_concurrent: int
    ttl_minutes: int
    cpu_limit: float
    memory_mb: int
    pids_limit: int


TIER_QUOTAS: dict[SandboxTier, TierQuota] = {
    "free": TierQuota(
        tier="free",
        max_concurrent=1,
        ttl_minutes=15,
        cpu_limit=1.0,
        memory_mb=512,
        pids_limit=64,
    ),
    "pro": TierQuota(
        tier="pro",
        max_concurrent=2,
        ttl_minutes=120,
        cpu_limit=1.0,
        memory_mb=1024,
        pids_limit=256,
    ),
    "enterprise": TierQuota(
        tier="enterprise",
        max_concurrent=5,
        ttl_minutes=180,
        cpu_limit=2.0,
        memory_mb=2048,
        pids_limit=512,
    ),
}


class LabTemplateSpec(BaseModel):
    id: LabTemplateId
    module: str
    title: str
    image: str
    summary: str
    archos_canvas_id: str
    needs_net_admin: bool = False
    default_shell: str = "/bin/bash"


SANDBOX_IMAGE = "registry.fly.io/crucible-sandboxes:v9"

LAB_TEMPLATES: dict[LabTemplateId, LabTemplateSpec] = {
    "lab0-free-range": LabTemplateSpec(
        id="lab0-free-range",
        module="M01",
        title="Free-Range Enterprise Cloud Range (Postgres 16 + PgBouncer + Redis + NGINX)",
        image=SANDBOX_IMAGE,
        summary="Open sandbox Firecracker Linux VM with ALL live daemons running (PostgreSQL 16, PgBouncer :6432, Redis 7, NGINX TLS 1.3 :8443), named checkpoints, and 1-click factory reset.",
        archos_canvas_id="dgm_spartan-lab1-core-engine",
        needs_net_admin=True,
    ),
    "lab1-core-engine": LabTemplateSpec(
        id="lab1-core-engine",
        module="M01",
        title="Lab 1 · Core Engine (Real Postgres 16, PgBouncer, Redis, FastAPI)",
        image=SANDBOX_IMAGE,
        summary="Live PostgreSQL 16 (15k rows), PgBouncer :6432, Redis :6379 & FastAPI :8000 with 4 randomized production faults.",
        archos_canvas_id="dgm_spartan-lab1-core-engine",
    ),
    "lab2-linux-tls": LabTemplateSpec(
        id="lab2-linux-tls",
        module="M05",
        title="Lab 2 · Real NGINX TLS 1.3, 502 Keepalive & Zero-Downtime Rollback",
        image=SANDBOX_IMAGE,
        summary="Live NGINX TLS 1.3 (:8443) proxying Uvicorn (:8000) with 3 randomized outages (502 keepalive race, weak TLS, 413 body limit).",
        archos_canvas_id="dgm_spartan-lab2-linux-tcp-tls-deploy",
        needs_net_admin=True,
    ),
    "lab3-lakehouse-wap": LabTemplateSpec(
        id="lab3-lakehouse-wap",
        module="M07",
        title="Lab 3 · Apache Iceberg Write-Audit-Publish & Idempotent Quarantine",
        image=SANDBOX_IMAGE,
        summary="Write-Audit-Publish data quality gates verified against hidden adversarial NULL/duplicate batches and DLQ quarantine.",
        archos_canvas_id="dgm_spartan-lab3-iac-aws-apache-data",
    ),
    "lab4-rag-acl": LabTemplateSpec(
        id="lab4-rag-acl",
        module="M08",
        title="Lab 4 · Enterprise Hybrid RAG, Pre-Filter ACLs & MCP Budget Guard",
        image=SANDBOX_IMAGE,
        summary="Multi-tenant pre-filter ACL retrieval audited by an immutable root-owned red-team probe plus bounded MCP budgets.",
        archos_canvas_id="dgm_spartan-lab4-ai-rag-mcp-evals",
    ),
    "lab5-raft-internals": LabTemplateSpec(
        id="lab5-raft-internals",
        module="M10",
        title="Lab 5 · LSM Storage Engine, Raft Consensus & Monotonic Fencing",
        image=SANDBOX_IMAGE,
        summary="Split-brain zombie leader fencing verified against hidden multi-term monotonic token adversarial sequences.",
        archos_canvas_id="dgm_spartan-lab5-internals-db-raft-llm",
    ),
    "lab6-k8s-ebpf": LabTemplateSpec(
        id="lab6-k8s-ebpf",
        module="M11",
        title="Lab 6 · Kubernetes, Cilium eBPF Zero-Trust Egress & PDB Drain Safety",
        image=SANDBOX_IMAGE,
        summary="Structural NetworkPolicy egress auditing (PgBouncer :6432 + DNS :53) and PodDisruptionBudget AZ drain verification.",
        archos_canvas_id="dgm_spartan-lab6-k8s-cilium-zerotrust-cdc",
    ),
    "lab7-linux-sre": LabTemplateSpec(
        id="lab7-linux-sre",
        module="M03",
        title="Lab 7 · Linux Kernel SRE: FD Limits, Lockfiles & DNS Forensics",
        image=SANDBOX_IMAGE,
        summary="Resolve EMFILE descriptor exhaustion, clear dead-PID lockfiles, and remediate poisoned internal service DNS.",
        archos_canvas_id="dgm_fail-metastable-failure",
    ),
    "lab8-scale-api": LabTemplateSpec(
        id="lab8-scale-api",
        module="M04",
        title="Lab 8 · 100k RPS Sliding-Window Rate Limiter & Idempotent Ledger",
        image=SANDBOX_IMAGE,
        summary="Fix per-key sliding-window burst throttling and Idempotency-Key double-charge races under hidden burst suites.",
        archos_canvas_id="dgm_rate-limiter",
    ),
    "lab9-iac-iam": LabTemplateSpec(
        id="lab9-iac-iam",
        module="M06",
        title="Lab 9 · AWS IAM Least-Privilege & Encrypted Terraform State Locks",
        image=SANDBOX_IMAGE,
        summary="Eliminate IAM wildcard privilege escalation (* / iam:PassRole) and harden Terraform S3 encrypted state locking.",
        archos_canvas_id="dgm_iac-terraform-state-locking-drift",
    ),
    "lab10-ai-gpu-mcp": LabTemplateSpec(
        id="lab10-ai-gpu-mcp",
        module="M09",
        title="Lab 10 · MCP Agent SSRF Firewall & H100 vLLM KV-Cache Tuning",
        image=SANDBOX_IMAGE,
        summary="Block IMDS/loopback/RFC1918 SSRF attacks on MCP tools and fix H100 vLLM CUDA OOM & prefix caching.",
        archos_canvas_id="dgm_llm-paged-kv-and-prefix-caching",
    ),
    "lab11-p0-capstone": LabTemplateSpec(
        id="lab11-p0-capstone",
        module="M12",
        title="Lab 11 · PRINCIPAL P0 CAPSTONE (Live NGINX + PgBouncer + Postgres 16)",
        image=SANDBOX_IMAGE,
        summary="SEV-0 3-layer cascading meltdown: diagnose & fix real Postgres 16, PgBouncer :6432, and NGINX TLS :8443 simultaneously.",
        archos_canvas_id="dgm_payment-system",
        needs_net_admin=True,
    ),
}


class ProvisionRequest(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    user_id: str = Field(..., min_length=2, max_length=128, pattern=r"^[a-zA-Z0-9_.:@-]+$")
    template_id: LabTemplateId
    tier: SandboxTier = "free"
    arm_blind_chaos: bool = False
    scenario_id: str | None = Field(default=None, max_length=80)


class SandboxSession(BaseModel):
    sandbox_id: str
    tenant_id: str
    user_id: str
    template_id: LabTemplateId
    module: str
    tier: SandboxTier
    status: SandboxStatus
    backend: str = "fly"
    fly_machine_id: str | None = None
    region: str | None = None
    scenario_id: str | None = None
    container_name: str
    network_name: str
    cpu_limit: float
    memory_mb: int
    pids_limit: int
    created_at: str
    expires_at: str
    terminal_ws_url: str
    terminal_token: str | None = None
    blind_fault_armed: bool = False
    blind_symptom: str | None = None
    security_profile: list[str] = Field(default_factory=list)


class ChaosInjectRequest(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=64)
    user_id: str = Field(..., min_length=2, max_length=128)
    seed: int | None = None
    scenario_id: str | None = Field(default=None, max_length=80)


class ChaosInjectResponse(BaseModel):
    sandbox_id: str
    status: Literal["armed"]
    symptom: str
    started_at: str


class VerifySandboxRequest(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=64)
    user_id: str = Field(..., min_length=2, max_length=128)


class VerifySandboxResponse(BaseModel):
    sandbox_id: str
    passed: bool
    elapsed_seconds: float
    revealed_fault: str | None = None
    remediation_hint: str | None = None
    receipt: dict[str, object]
