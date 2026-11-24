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
        cpu_limit=0.5,
        memory_mb=512,
        pids_limit=64,
    ),
    "pro": TierQuota(
        tier="pro",
        max_concurrent=2,
        ttl_minutes=90,
        cpu_limit=1.5,
        memory_mb=2048,
        pids_limit=256,
    ),
    "enterprise": TierQuota(
        tier="enterprise",
        max_concurrent=5,
        ttl_minutes=180,
        cpu_limit=4.0,
        memory_mb=4096,
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
        title="Lab 1 · Core Engine (Nginx, FastAPI, PgBouncer, Postgres 16, Redis)",
        image="ghcr.io/jasonteixeira/spartan-lab1-sre:latest",
        summary=(
            "Full 11-service production stack with Prometheus/Grafana, "
            "10 chaos faults, and Postgres lock/query forensics."
        ),
        archos_canvas_id="dgm_spartan-lab1-core-engine",
    ),
    "lab2-linux-tls": LabTemplateSpec(
        id="lab2-linux-tls",
        module="M05",
        title="Lab 2 · Linux Kernel, TCP/IP, TLS & Zero-Downtime Rollback",
        image="ghcr.io/jasonteixeira/spartan-lab2-linux:latest",
        summary=(
            "Isolated netem/tc traffic shaping, tcpdump packet forensics, "
            "TLS handshake debugging, and zero-downtime canary deploys."
        ),
        archos_canvas_id="dgm_spartan-lab2-linux-tcp-tls-deploy",
        needs_net_admin=True,
    ),
    "lab3-lakehouse-wap": LabTemplateSpec(
        id="lab3-lakehouse-wap",
        module="M07",
        title="Lab 3 · Terraform IaC, Apache Iceberg WAP & ClickHouse Outage",
        image="ghcr.io/jasonteixeira/spartan-lab3-data:latest",
        summary=(
            "Write-Audit-Publish data quality gates, schema-drift quarantine, "
            "and ClickHouse OLAP partition recovery."
        ),
        archos_canvas_id="dgm_spartan-lab3-iac-aws-apache-data",
    ),
    "lab4-rag-acl": LabTemplateSpec(
        id="lab4-rag-acl",
        module="M08",
        title="Lab 4 · Enterprise Hybrid RAG, Pre-Filter ACLs, MCP & Evals",
        image="ghcr.io/jasonteixeira/spartan-lab4-ai:latest",
        summary=(
            "Hybrid BM25+Vector retrieval with zero-leak ACL pre-filtering, "
            "BEIR ranking evals, and bounded agent tool loops."
        ),
        archos_canvas_id="dgm_spartan-lab4-ai-rag-mcp-evals",
    ),
    "lab5-raft-internals": LabTemplateSpec(
        id="lab5-raft-internals",
        module="M10",
        title="Lab 5 · Pure-Code LSM Storage Engine, Raft Consensus & KV Cache",
        image="ghcr.io/jasonteixeira/spartan-lab5-internals:latest",
        summary=(
            "WAL recovery, SSTable compaction storms, Raft leader election "
            "split-brain fencing, and PagedAttention KV-cache math."
        ),
        archos_canvas_id="dgm_spartan-lab5-internals-db-raft-llm",
    ),
    "lab6-k8s-ebpf": LabTemplateSpec(
        id="lab6-k8s-ebpf",
        module="M11",
        title="Lab 6 · Kubernetes, Cilium eBPF Zero-Trust, CDC & Strangler Canary",
        image="ghcr.io/jasonteixeira/spartan-lab6-k8s:latest",
        summary=(
            "NetworkPolicy isolation, eBPF traffic observability, "
            "Debezium CDC backfill recovery, and zero-downtime strangler cutover."
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
