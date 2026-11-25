"""Strict Pydantic v2 models & per-tier resource quotas for multi-tenant sandboxes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

LabTemplateId = Literal[
    "lab1-core-engine",
    "lab2-linux-tls",
    "lab3-lakehouse-wap",
    "lab4-rag-acl",
    "lab5-raft-internals",
    "lab6-k8s-ebpf",
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
        ttl_minutes=30,
        cpu_limit=1.0,
        memory_mb=512,
        pids_limit=64,
    ),
    "pro": TierQuota(
        tier="pro",
        max_concurrent=2,
        ttl_minutes=90,
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


LAB_TEMPLATES: dict[LabTemplateId, LabTemplateSpec] = {
    "lab1-core-engine": LabTemplateSpec(
        id="lab1-core-engine",
        module="M01",
        title="Lab 1 · Core Engine (Real Postgres 16, PgBouncer, Redis, FastAPI)",
        image="registry.fly.io/crucible-sandboxes:latest",
        summary=(
            "Live PostgreSQL 16 (15k rows), PgBouncer :6432, Redis :6379 & FastAPI :8000 "
            "inside a dedicated Firecracker MicroVM with blind query-plan & pool starvation faults."
        ),
        archos_canvas_id="dgm_spartan-lab1-core-engine",
    ),
    "lab2-linux-tls": LabTemplateSpec(
        id="lab2-linux-tls",
        module="M05",
        title="Lab 2 · Linux Kernel, Real NGINX TLS 1.3 & Zero-Downtime Rollback",
        image="registry.fly.io/crucible-sandboxes:latest",
        summary=(
            "Live NGINX TLS 1.3 (:8443) proxying Uvicorn (:8000), OpenSSL handshake forensics, "
            "keepalive race debugging, and K8s preStop drain verification."
        ),
        archos_canvas_id="dgm_spartan-lab2-linux-tcp-tls-deploy",
        needs_net_admin=True,
    ),
    "lab3-lakehouse-wap": LabTemplateSpec(
        id="lab3-lakehouse-wap",
        module="M07",
        title="Lab 3 · Terraform IaC, Apache Iceberg WAP & Quarantine Gate",
        image="registry.fly.io/crucible-sandboxes:latest",
        summary=(
            "Write-Audit-Publish data quality gates verified against hidden adversarial "
            "poisoned batches and DLQ quarantine contracts."
        ),
        archos_canvas_id="dgm_spartan-lab3-iac-aws-apache-data",
    ),
    "lab4-rag-acl": LabTemplateSpec(
        id="lab4-rag-acl",
        module="M08",
        title="Lab 4 · Enterprise Hybrid RAG, Pre-Filter ACLs & MCP Budget Guard",
        image="registry.fly.io/crucible-sandboxes:latest",
        summary=(
            "Multi-tenant pre-filter ACL retrieval audited by an immutable root-owned red-team "
            "probe plus bounded MCP tool budget enforcement."
        ),
        archos_canvas_id="dgm_spartan-lab4-ai-rag-mcp-evals",
    ),
    "lab5-raft-internals": LabTemplateSpec(
        id="lab5-raft-internals",
        module="M10",
        title="Lab 5 · LSM Storage Engine, Raft Consensus & Monotonic Fencing",
        image="registry.fly.io/crucible-sandboxes:latest",
        summary=(
            "Split-brain zombie leader fencing verified against hidden multi-term "
            "monotonic token adversarial sequences."
        ),
        archos_canvas_id="dgm_spartan-lab5-internals-db-raft-llm",
    ),
    "lab6-k8s-ebpf": LabTemplateSpec(
        id="lab6-k8s-ebpf",
        module="M11",
        title="Lab 6 · Kubernetes, Cilium eBPF Zero-Trust Egress & PDB Drain Safety",
        image="registry.fly.io/crucible-sandboxes:latest",
        summary=(
            "Structural NetworkPolicy egress auditing (PgBouncer :6432 + DNS :53) and "
            "PodDisruptionBudget AZ drain verification."
        ),
        archos_canvas_id="dgm_spartan-lab6-k8s-cilium-zerotrust-cdc",
    ),
}


class ProvisionRequest(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    user_id: str = Field(..., min_length=2, max_length=128, pattern=r"^[a-zA-Z0-9_.:@-]+$")
    template_id: LabTemplateId
    tier: SandboxTier = "free"
    arm_blind_chaos: bool = False


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
