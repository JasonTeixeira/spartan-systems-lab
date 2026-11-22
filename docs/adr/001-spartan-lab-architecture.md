# ADR-001: Stacked 5-Lab Architecture & Network Segmentation Baseline

- **Date:** 2026-11-22
- **Status:** Accepted
- **Lab / Component:** Platform-Wide (Labs 1-5)

## 1. Context & Constraints
We need a single local homelab monorepo on an Apple M3 Max (64 GB RAM, ~83 GiB free disk) that builds real muscle memory across Linux, Python, PostgreSQL, Networking, Cloud IaC (`aws-emulator`), Streaming/OLAP, AI/MLOps, and Kubernetes/Chaos without wasting weeks on disconnected toy apps or exhausting disk space.

## 2. Decision
1. **One Progressive Monorepo (5 Stacked Labs):** Lab 1 (Core Engine + Linux SRE Toolbox) -> Lab 2 (Cloud Data Pipelines + FinOps) -> Lab 3 (Scaled Vector RAG + MLOps) -> Lab 4 (Pure-Code LSM + Raft + Zero-Copy) -> Lab 5 (Kind K8s + Cilium eBPF + Zero-Trust + Blind Chaos Roulette).
2. **Private vs. Edge Network Isolation from Day 1:** In Lab 1, Nginx sits on both `edge_net` and `app_net`; Postgres, PgBouncer, and Redis sit strictly on `private_data_net` (mirroring real public vs. private VPC subnets).
3. **Spartan Active-Recall Discipline:** Drills under `drills/` ship as unimplemented stubs with strict `pytest` specs so every core Python/SQL pattern is written by hand without AI ghostwriting.

## 3. Consequences & Trade-Offs
- **Positive:** One coherent portfolio repository with real CI (`ruff`, `mypy`, `pytest`), real ADRs, and real outage post-mortems.
- **Negative:** Local emulators (`aws-emulator`, `kind`, `ollama`) cannot fully replicate real AWS IAM edge cases or NVIDIA CUDA HBM physics.
- **Mitigation:** Schedule two short (~$15 total) live-fire sprints after Lab 5 (ephemeral AWS Terraform fire drill + 3-hour RunPod vLLM/nsys sprint).
