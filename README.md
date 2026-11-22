# Spartan Systems Lab

**Hands-on, terminal-first mastery of Linux, Python, PostgreSQL, Networking, Cloud IaC, Data Pipelines, AI/MLOps, and SRE Chaos Engineering.**

> *Train harder in the lab than anything an interview or production outage can throw at you.*

## Reference Manuals (`docs/manuals/`)
- **Manual #1 (Primitives & 22 Daily Tasks):** `docs/manuals/PYTHON_AND_SQL_PRODUCTION_MASTERY_GUIDE.pdf` (`.md` companion included)
- **Manual #2 (Homelab & Enterprise Systems Blueprint):** `docs/manuals/HOME_LAB_SYSTEM_ARCHITECTURE_BLUEPRINT.pdf` (`.md` companion included)

## Repository Layout
```text
spartan-systems-lab/
├── docs/
│   ├── manuals/        # Both printable PDFs & Markdown field manuals
│   ├── adr/            # 1-page Architecture Decision Records (with real math & trade-offs)
│   └── postmortems/    # Outage war-room logs (MTTD, MTTR, root cause, permanent fix)
├── drills/
│   ├── python-dsa/     # Daily 15-min cold Python & 14-template reps (pytest-verified)
│   ├── sql/            # Daily 15-min cold SQL reps against real Postgres
│   └── linux/          # 60-second Linux SRE triage & network forensics drills
├── lab-1-core-engine/  # Nginx + FastAPI + PgBouncer + Postgres 16 + Redis + Linux SRE Toolbox + k6
├── lab-2-cloud-finops/ # [Next] aws-emulator (S3/SQS/IAM) + Terraform + Redpanda + ClickHouse + Grafana
├── lab-3-ai-mlops/     # [Next] Qdrant + Ollama + LiteLLM + MLflow + Phoenix/Promptfoo + Anomaly ML
├── lab-4-internals/    # [Next] Pure-code LSM-Tree + 3-Node Raft + Zero-Copy sendfile benchmark
├── lab-5-k8s-chaos/    # [Next] 3-node Kind + Cilium eBPF + ArgoCD + Vault + Blind Chaos Roulette
└── tests/              # Automated unit & integration tests (run locally & in CI)
```

## Quick Start (Lab 1)
```bash
# 1. Install Python deps (managed by uv)
make setup

# 2. Run local CI checks (ruff + mypy + unit tests)
make ci

# 3. Boot Lab 1 (requires Docker Desktop running)
make up

# 4. Seed 100k rows (or 10M rows for the Scaling Laws benchmark)
make seed ROWS=100000

# 5. Open your Linux SRE Toolbox shell (ss, tcpdump, strace, dig, vmstat, iostat, psql)
make sre-shell

# 6. Inject a Day-1 outage and diagnose it cold
make chaos SCENARIO=lock-storm
```

## The Daily Spartan Loop (75-90 Minutes)
1. **15 min Cold Warmup:** Solve 1 timed Python/DSA drill (`make drill-py`) + 1 SQL drill (`drills/sql/`) with **zero AI autocomplete**.
2. **45-60 min Lab Combat:** Build or fix 1 vertical slice, hit it with `k6`, measure real numbers (`EXPLAIN ANALYZE`, `ss -s`, `strace`, `tcpdump`, RAM, p99).
3. **10 min Lock It In:** Commit clean code, log a 10-line ADR/post-mortem, and defend your design trade-offs out loud.
