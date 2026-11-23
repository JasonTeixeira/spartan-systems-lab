# Master Documentation & Toolkit Index (`spartan-systems-lab`)

Everything committed in this monorepo, organized from **Primitives -> Frameworks -> Failure Forensics -> Automation -> Reusable On-the-Job Tools -> Live Labs**.

---

## 0. Start Here (Operator Manual & Visual Progress Tracker)
- **`docs/HOW_TO_USE_THIS_LAB.md`** — Day-0 operator workflow, automated `make review` code/security/CVE reviewer, 5-Axis Principal Optimizer Rubric, ranked Python library stack (~25 core libraries), `uv` patching & container upgrade workflow, and audit-trail discipline.
- **`docs/mastery_tracker.html`** — Interactive browser mastery dashboard (double-click or `open docs/mastery_tracker.html`) tracking all 6 Labs, 10 Archetypes, 12 DDIA Chapters, 12 Data Safeguards, 12 Automation Archetypes, 22 Daily Loops, Failure Drills, and 8 Mini-System Katas with CSV export.

## 1. Field Manuals (`docs/manuals/`)
- **Manual #1 (Primitives, 126 Concepts, 22 Daily Loops, 5 Scaling Laws, 6 Master AHAs):**
  - `docs/manuals/PYTHON_AND_SQL_PRODUCTION_MASTERY_GUIDE.pdf` (9 pages) & `.md`
- **Manual #2 (Homelab & Enterprise Systems Blueprint, 58 Components, 47 Architectures):**
  - `docs/manuals/HOME_LAB_SYSTEM_ARCHITECTURE_BLUEPRINT.pdf` (5 pages) & `.md`

## 2. Core Mastery Frameworks (`docs/`)
- **`docs/DATA_LIFECYCLE_AND_SERVER_FUNDAMENTALS.md`** — The 6-Stage Data Lifecycle (*Fundamentals of Data Engineering*), 4-Question Visual DB Decision Tree & 5 Locked-In Data Stacks (3NF / Medallion / Star Schema / OBT / KV+Vector), SCD Type 2 / Grain / Point-in-Time `ASOF JOIN` / Write-Audit-Publish (WAP), 12 Local-vs-Cloud Data Safeguards, 5 Hardware Server Archetypes, and Self-Hosted CI Runners (ARC) / Forgejo.
- **`docs/JUDGMENT_AND_COMMUNICATION_FRAMEWORKS.md`** — The 45-Minute Live System Design Clock (6 non-random clarifying questions + 7 physics constants), 6 Principal Judgment & Trade-Off Decision Matrices (Reversibility, Build/Buy/OSS, Simple->Scalable Thresholds, AI/ML Judgment Tree, Tech Debt Triage, Pre-Mortem Inversion), and 2 Communication Frameworks (Technical Peers + C-Suite BLUF / Executive Translation Dictionary).
- **`docs/PRINCIPAL_FRAMEWORKS.md`** — 10 Universal System Archetypes (+ WebRTC Voice AI + VM/Container/MicroVM), Full 12-Chapter DDIA Audit, 5 Principal Thinking Frameworks, Enterprise Architecture Frameworks (C4, Well-Architected, Distributed Pattern Kit, Fitness Functions), Google SRE Mastery (SLI/SLO/Error Budgets, Golden Signals/RED/USE, Burn-Rate Alerting, Toil, ICS), 5-Layer QA & DR Standard, Build-in-Public Brand Engine, and 6 Additive Modular Packs.
- **`docs/FAILURE_MODES_AND_PERFORMANCE.md`** — Brendan Gregg's 5 Scientific Performance Models (USE, RED, TSA, On-CPU vs Off-CPU, Pragmatic eBPF) + **40 Mapped Production Failures across 8 Domains (~96-98% real-world incident coverage)**.
- **`docs/PYTHON_AUTOMATION_AND_ORCHESTRATION.md`** — The 12 Universal Enterprise & Consulting Automation Archetypes, 7 Iron Laws of Unbreakable Python Automation, Confidence-Threshold HITL Routing, and the Orchestration Selection Matrix (Cron vs Queues vs Airflow/Dagster vs Temporal vs GitOps/Terraform/Ansible vs n8n/Playwright).
- **`docs/AI_ML_AND_LLM_MASTERY.md`** — Complete AI/ML & LLM Engineering Specialty Blueprint: Hugging Face (`transformers`/`peft`/`datasets`/`sentence-transformers`), Inference (`Ollama`/`mlx-lm`/`vLLM`/`LiteLLM` + KV-cache/TTFT/ITL), Embeddings & 6 Proven Production RAG Patterns (Qdrant/`pgvector`/HNSW/Reranking), LangGraph vs. Pure Python + MCP Agents, 5-Layer AI/LLM/Behavioral ML Eval Pyramid, and the 6-Repo Surgical Extraction Map (`nn-zero-to-hero`, `LLMs-from-scratch`, `Made-With-ML`, `RAG_Techniques`, `ai-engineering-hub`, `applied-ml`).

## 3. Evidence, Decisions & Proof Artifacts (`docs/`)
- `docs/rfc/` — 1-page Business-to-Architecture RFCs
- `docs/adr/` — Architecture Decision Records (`000-template.md`, `001-spartan-lab-architecture.md`)
- `docs/runbooks/` — 3:00 AM copy-paste triage runbooks
- `docs/benchmarks/` — Reproducible Before/After `$/month` & p99 savings receipts
- `docs/incidents/` — Timestamped forensic bundles captured via `make snapshot-incident NAME=...`
- `docs/postmortems/` — Blameless post-mortems (`000-template.md`)

## 4. Reusable On-the-Job Tools (`tools/` & `scripts/`)
- **`tools/sql-diagnostics/pg_xray.sql`** — Read-only Production Postgres X-Ray (locks, `idle in transaction`, dead-tuple bloat, seq scans, buffer cache hit ratio, XID wraparound age, `pg_stat_statements`).
- **`tools/linux-triage.sh`** — Safe 60-second read-only Linux triage collector (USE/TSA, cgroup v2 throttling, `df -i`, `ss -s`, `ip route`, D-state procs, `dmesg`).
- **`tools/finops_calc.py`** — Tested Python CLI for Little's Law capacity, LLM semantic-cache/routing dollar savings, and GPU VRAM/KV-cache sizing.
- **`scripts/snapshot_incident.sh`** — One-command incident evidence archiver before running `make reset`.

## 5. Active Hands-On Lab & Cold Drills
- **`lab-1-core-engine/`** — 11-service live stack (`nginx`, `api` + `/metrics`, `pgbouncer`, `postgres` + 3 Executive FinOps SQL views, `redis`, `metabase` Executive BI `:3000`, `prometheus` `:9090`, `grafana` auto-provisioned 6-panel dashboard `:3001`, `postgres-exporter`, `redis-exporter`, `sre-toolbox`), `seed_events.py`, `load_k6.js`, `chaos_lab1.sh`.
- **`drills/`** — Cold unassisted Python/DSA stubs (`drills/python-dsa/`), SQL drills (`drills/sql/`), and Linux triage drills (`drills/linux/`).
