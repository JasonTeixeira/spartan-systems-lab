# Spartan Systems Lab

**Hands-on, terminal-first mastery of Linux, Python, PostgreSQL, Networking, Cloud IaC, Apache Data Platforms, Production AI/Agents/MCP/MLOps, Kubernetes, and SRE Chaos Engineering.**

> *Train 10x harder in the lab so interviews and 3:00 AM production war rooms feel easy.*

## Reference Manuals & Frameworks (`docs/`)
- **Principal Thinking Frameworks & Visual Map:** `docs/PRINCIPAL_FRAMEWORKS.md` *(10 Archetypes -> 30+ Interview Systems, Full 12-Chapter DDIA Audit, 5 Thinking Frameworks, 4 Executive Proof Docs, Nightmare Mode)*
- **Manual #1 (Primitives & 22 Daily Tasks):** `docs/manuals/PYTHON_AND_SQL_PRODUCTION_MASTERY_GUIDE.pdf` (`.md` included)
- **Manual #2 (Homelab & Enterprise Systems Blueprint):** `docs/manuals/HOME_LAB_SYSTEM_ARCHITECTURE_BLUEPRINT.pdf` (`.md` included)

## The 6 Stacked Labs (100% Coverage of All 10 System Archetypes & All 12 DDIA Chapters)

| Lab | Primary Focus | Core Stack & What You Master |
| :--- | :--- | :--- |
| **Lab 1** *(Active)* | **Core Engine, Clean Code Arch, DB Internals & Linux Forensics** | FastAPI (Hexagonal arch + WebSockets/SSE), Postgres 16 + PgBouncer + PostGIS, Redis, Nginx, Linux SRE Toolbox, `k6`, GitHub CI (`ruff`/`mypy`/`pytest`), **all 22 daily tasks + 10M rows + live DDIA Lost Update/Write Skew anomalies** |
| **Lab 2** | **On-Prem Networking (Debian + Rocky/RHEL), Edge/CDN, Security & Deployments** | 4-node Linux Firewall (`nftables`), DNS, TLS/HTTPS & CDN caching (Nginx/Caddy), SSH Bastion, Protobuf/gRPC schema evolution, real Linux/VPS + Docker CI/CD deployment & zero-downtime rollback |
| **Lab 3** | **Cloud Infra (Core 12 AWS), Apache Data Platform, Email/Blob & Dashboards** | `aws/aws-emulator` + Terraform, Apache Kafka/Redpanda, ClickHouse, MinIO + **Apache Iceberg/Arrow/Parquet** + chunked media/blob pipeline, **Airflow + PySpark + DuckDB**, **Mailpit** email pipeline, **Prometheus + Grafana + Loki + OTel** |
| **Lab 4** *(AI/ML Spike)* | **Production AI, Agents, MCP, Scaled Vector RAG & MLOps** | **Production MCP Server**, stateful Agentic Workflows + guardrails, Qdrant (hybrid dense+BM25+RBAC), Ollama, LiteLLM, Redis Semantic Cache, MLflow (LightGBM/PyTorch anomaly/ranking model + drift), Phoenix/Promptfoo eval gates, AI Grafana dashboards, 3-hr RunPod vLLM/GPU sprint |
| **Lab 5** | **Under-the-Hood Database & Consensus Internals** *(Pure Code)* | 300-line **LSM-Tree** (WAL/MemTable/SSTable/Bloom/Compaction), **3-Node Raft** over raw TCP, **Zero-copy `sendfile`** benchmark |
| **Lab 6** | **Kubernetes, Zero-Trust, Brownfield Migration & Blind Chaos Roulette** | 3-node `kind`, Cilium eBPF/Hubble/Tetragon, ArgoCD GitOps, OpenBao/Vault, Keycloak OIDC, Trivy, Debezium CDC + Envoy Strangler Fig, Chaos Mesh, **12-Outage Blind Chaos Roulette**, 1 ephemeral real-AWS Terraform live-fire deploy |

## Repository Layout
```text
spartan-systems-lab/
├── docs/
│   ├── PRINCIPAL_FRAMEWORKS.md # 10 Archetypes, 12 DDIA Chapters, 5 Frameworks, Nightmare Mode
│   ├── manuals/                # Both printable PDFs & Markdown field manuals
│   ├── rfc/                    # 1-page business-to-architecture RFCs
│   ├── adr/                    # Architecture Decision Records (with real math & trade-offs)
│   ├── runbooks/               # 3:00 AM copy-paste triage runbooks
│   ├── benchmarks/             # Before/After $/month & p99 proof receipts
│   └── postmortems/            # Outage war-room logs (MTTD, MTTR, root cause, fix)
├── drills/
│   ├── python-dsa/             # Daily timed cold Python & 14-template reps (pytest-verified)
│   ├── sql/                    # Daily timed cold SQL & DDIA isolation drills against live Postgres
│   └── linux/                  # 60-second Linux SRE triage & network forensics drills
├── lab-1-core-engine/          # Active Lab 1 stack
└── tests/                      # Automated unit & integration tests (local & CI)
```

## Quick Start (Lab 1)
```bash
make setup                  # Sync Python env via uv
make ci                     # Run ruff + mypy + pytest tests/
make drill-py               # Run Day-1 cold Python drills (red until YOU implement them!)
make up                     # Boot Lab 1 stack (requires Docker Desktop running)
make seed ROWS=250000       # Stream rows via COPY FROM STDIN (scale up to 10,000,000)
make sre-shell              # Enter Linux SRE toolbox (ss, tcpdump, strace, dig, tc, iostat)
make chaos SCENARIO=lock-storm
```

## The Universal 6-Step Spartan Loop (Run On Every Lab)
1. **SPEC (10m):** Business goal + QPS/RAM/Storage/Cost math + Simple vs. Scalable trade-off.
2. **BUILD:** Clean Domain/Adapter code + DB migrations + Docker/Terraform + `pytest`/CI.
3. **INSTRUMENT:** Structured JSON logs + Prometheus RED/AI metrics + Grafana 4-row dashboard.
4. **STRESS:** Hit with `k6` / 10M rows / eval suite until something actually breaks.
5. **BREAK & TRACE:** Inject blind/compound chaos -> diagnose cold from terminal (`ss`/`strace`/`tcpdump`/`EXPLAIN`).
6. **DEFEND (10m):** Log benchmark/post-mortem + survive a 5-min hostile Staff-interview grill.
