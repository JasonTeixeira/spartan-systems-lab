# Master Documentation & Toolkit Index (`spartan-systems-lab`)

Everything committed in this monorepo, organized from **Primitives -> Frameworks -> Failure Forensics -> Automation -> Reusable On-the-Job Tools -> Live Labs**.

---

## 0. Start Here (Visual Atlas v2, Tool Belt, Linear Syllabus, Operator Manual & Tracker)
- **`docs/index.html`** (`make portal`) — **Interactive Visual Architecture Atlas v2.0** (offline browser & GitHub Pages): **560 concrete units across 159 canonical pattern skills (9 disciplines)** synced with **ArchOS (`http://127.0.0.1:5180/`)**, **3 standalone SVG architecture blueprints (`docs/diagrams/`)**, expandable **12-Module Daily Rep Sprint Board** (1-click deep-linked to **178 standardized animated ArchOS canvases** including **12 dedicated `Spartan Labs Infra` & Chaos canvases** + **52 Titanium Wave 1–4 Failure/Migration/GPU/LLM/IaC/Security canvases** + infinite Nightmare-Mode reset), **Visual IaC & 8-Stage CI/CD Pipeline Maps**, **Searchable Master Tool Belt** (including React/React Native/Frontend), **GPU Silicon / Crypto / NIST / MITRE Cards**, 6-Role Switcher ($200k–$600k+), and 5-lane End-to-End Platform Diagram.
- **`docs/diagrams/`** — Standalone publication-grade SVG architecture blueprints (`01-network-vpc-request-flow.svg`, `02-data-lifecycle-bi-pipeline.svg`, `03-ai-rag-mcp-eval-architecture.svg`) embedded in `docs/index.html` and served live on GitHub Pages.
- **`docs/TOOLBELT.md`** — Complete searchable Master Tool Belt (Linux/SRE, Python/QA, Data/BI, AI/ML/LLM, Cloud/IaC/K8s, Security, and **React/Next.js/React Native/Frontend**) with 1-line commands — ready for `spartan-mcp` Step 2.
- **`docs/LINEAR_SYLLABUS.md`** — **The 12-Module Linear Compounding Syllabus** (`M01 -> M12`, 4 parallel daily tracks, Boss Fight gates, Constraint-First LeetCode-100x method, and 10 "30-Year Veteran" Battle Scars).
- **`docs/mastery_tracker.html`** (`make tracker`) — Interactive browser mastery checklist tracking all 6 Labs, 10 Archetypes, 12 DDIA Chapters, 12 Data Safeguards, 12 Automation Archetypes, 22 Daily Loops, Failure Drills, and 8 Mini-System Katas with CSV export.
- **`docs/HOW_TO_USE_THIS_LAB.md`** — Day-0 operator workflow, automated `make review` code/security/CVE reviewer, 5-Axis Principal Optimizer Rubric, ranked Python library stack (~25 core libraries), `uv` patching & container upgrade workflow, and audit-trail discipline.

## 1. Field Manuals (`docs/manuals/`)
- **Manual #1 (Primitives, 126 Concepts, 22 Daily Loops, 5 Scaling Laws, 6 Master AHAs):**
  - `docs/manuals/PYTHON_AND_SQL_PRODUCTION_MASTERY_GUIDE.pdf` (9 pages) & `.md`
- **Manual #2 (Homelab & Enterprise Systems Blueprint, 58 Components, 47 Architectures):**
  - `docs/manuals/HOME_LAB_SYSTEM_ARCHITECTURE_BLUEPRINT.pdf` (5 pages) & `.md`

## 2. Core Mastery Frameworks (`docs/`)
- **`docs/DATA_LIFECYCLE_AND_SERVER_FUNDAMENTALS.md`** — The 6-Stage Data Lifecycle (*Fundamentals of Data Engineering*), 4-Question Visual DB Decision Tree & 5 Locked-In Data Stacks (3NF / Medallion / Star Schema / OBT / KV+Vector), SCD Type 2 / Grain / Point-in-Time `ASOF JOIN` / Write-Audit-Publish (WAP), 12 Local-vs-Cloud Data Safeguards, 5 Hardware Server Archetypes, and Self-Hosted CI Runners (ARC) / Forgejo.
- **`docs/JUDGMENT_AND_COMMUNICATION_FRAMEWORKS.md`** — The 45-Minute Live System Design Clock (6 non-random clarifying questions + 7 physics constants), 6 Principal Judgment & Trade-Off Decision Matrices (Reversibility, Build/Buy/OSS, Simple->Scalable Thresholds, AI/ML Judgment Tree, Tech Debt Triage, Pre-Mortem Inversion), and 2 Communication Frameworks (Technical Peers + C-Suite BLUF / Executive Translation Dictionary).
- **`docs/LEADERSHIP_AND_EXEC_MASTERY.md`** — **Top 0.1% Executive, Org Scale (10 -> 1,000+), Content Factory & High-Ticket Consulting Playbook**: Working Backwards PR/FAQ, Minto Pyramid/BLUF, P&L/Rule-of-40/Margin, Team Topologies & WBR/QBR/AOP, DACI/Critical Path/RAID (20% of PMP that works), Hiring Bar & Radical Candor SBI, Pre-Wiring & Vocal Presence, 8 STAR-L Cards, **1-Rep-to-5-Assets LinkedIn/YouTube/IG Content Factory (12 M01–M12 Episode Blueprints)**, and **Enterprise MEDDPICC Discovery + Paid $25k–$150k Value-Based Consulting Playbook**.
- **`docs/PRINCIPAL_FRAMEWORKS.md`** — 10 Universal System Archetypes (+ WebRTC Voice AI + VM/Container/MicroVM), Full 12-Chapter DDIA Audit, 5 Principal Thinking Frameworks, Enterprise Architecture Frameworks (C4, Well-Architected, Distributed Pattern Kit, Fitness Functions), Google SRE Mastery (SLI/SLO/Error Budgets, Golden Signals/RED/USE, Burn-Rate Alerting, Toil, ICS), 5-Layer QA & DR Standard, Build-in-Public Brand Engine, and 6 Additive Modular Packs.
- **`docs/FAILURE_MODES_AND_PERFORMANCE.md`** — Brendan Gregg's 5 Scientific Performance Models (USE, RED, TSA, On-CPU vs Off-CPU, Pragmatic eBPF) + **40 Mapped Production Failures across 8 Domains (~96-98% real-world incident coverage)**.
- **`docs/PYTHON_AUTOMATION_AND_ORCHESTRATION.md`** — The 12 Universal Enterprise & Consulting Automation Archetypes, 7 Iron Laws of Unbreakable Python Automation, Confidence-Threshold HITL Routing, and the Orchestration Selection Matrix (Cron vs Queues vs Airflow/Dagster vs Temporal vs GitOps/Terraform/Ansible vs n8n/Playwright).
- **`docs/AI_ML_AND_LLM_MASTERY.md`** — Complete AI/ML & LLM Engineering Specialty Blueprint: Hugging Face (`transformers`/`peft`/`datasets`/`sentence-transformers`), Inference (`Ollama`/`mlx-lm`/`vLLM`/`LiteLLM` + KV-cache/TTFT/ITL), Embeddings & 6 Proven Production RAG Patterns (Qdrant/`pgvector`/HNSW/Reranking), LangGraph vs. Pure Python + MCP Agents, 5-Layer AI/LLM/Behavioral ML Eval Pyramid, and the 6-Repo Surgical Extraction Map (`nn-zero-to-hero`, `LLMs-from-scratch`, `Made-With-ML`, `RAG_Techniques`, `ai-engineering-hub`, `applied-ml`).
- **`docs/DEEP_SPECIALTIES_IAC_API_ML_SECURITY_CERTS.md`** — **+78 Deep Specialist Units** (362 -> 440 total): Production IaC Mastery (Terraform state surgery/drift/Checkov/Packer/Ansible/Helm/Crossplane), Clean Python (Cosmic Python) & Scale API Architecture, 7-Step ML System Design + 8 Canonical ML Systems, Deep TCP/IP & CISSP/Zero-Trust/OWASP/STRIDE Security Architecture, and AWS SAP-C02 / GenAI Pro / GCP Cert Delta.

## 3. Evidence, Decisions & Proof Artifacts (`docs/`)
- `docs/rfc/` — 1-page Business-to-Architecture RFCs
- `docs/adr/` — Architecture Decision Records (`000-template.md`, `001-spartan-lab-architecture.md`)
- `docs/runbooks/` — 3:00 AM copy-paste triage runbooks
- `docs/benchmarks/` — Reproducible Before/After `$/month` & p99 savings receipts
- `docs/incidents/` — Timestamped forensic bundles captured via `make snapshot-incident NAME=...`
- `docs/postmortems/` — Blameless post-mortems (`000-template.md`)

## 4. Reusable On-the-Job Tools (`mcp_server/`, `tools/` & `scripts/`)
- **`mcp_server/` (`make mcp` — [README](../mcp_server/README.md))** — Personal Principal Engineer MCP Server with **7 tools** (`finops_estimate`, `toolbelt_and_runbook_lookup`, `qa_and_code_review`, approval-gated `generate_dashboard_pack`, `visualize_infra_and_cicd`, `archos_canvas_lookup`, and approval-gated `infra_to_archos_canvas`) ready to plug into Claude Code, Cursor, or Antigravity.
- **`tools/sql-diagnostics/pg_xray.sql`** — Read-only Production Postgres X-Ray (locks, `idle in transaction`, dead-tuple bloat, seq scans, buffer cache hit ratio, XID wraparound age, `pg_stat_statements`).
- **`tools/linux-triage.sh`** — Safe 60-second read-only Linux triage collector (USE/TSA, cgroup v2 throttling, `df -i`, `ss -s`, `ip route`, D-state procs, `dmesg`).
- **`tools/finops_calc.py`** — Tested Python CLI for Little's Law capacity, LLM semantic-cache/routing dollar savings, and GPU VRAM/KV-cache sizing.
- **`scripts/snapshot_incident.sh`** — One-command incident evidence archiver before running `make reset`.

## 5. Active Hands-On Lab & Cold Drills
- **`lab-1-core-engine/`** — 11-service live stack (`nginx`, `api` + `/metrics`, `pgbouncer`, `postgres` + 3 Executive FinOps SQL views, `redis`, `metabase` Executive BI `:3000`, `prometheus` `:9090`, `grafana` auto-provisioned 6-panel dashboard `:3001`, `postgres-exporter`, `redis-exporter`, `sre-toolbox`), `seed_events.py`, `load_k6.js`, `chaos_lab1.sh`.
- **`drills/`** — Cold unassisted Python/DSA stubs (`drills/python-dsa/`), SQL drills (`drills/sql/`), and Linux triage drills (`drills/linux/`).
