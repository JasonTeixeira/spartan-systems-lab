# Master Documentation & Toolkit Index (`spartan-systems-lab`)

Everything committed in this monorepo, organized from **Primitives -> Frameworks -> Failure Forensics -> Automation -> Reusable On-the-Job Tools -> Live Labs**.

---

## 1. Field Manuals (`docs/manuals/`)
- **Manual #1 (Primitives, 126 Concepts, 22 Daily Loops, 5 Scaling Laws, 6 Master AHAs):**
  - `docs/manuals/PYTHON_AND_SQL_PRODUCTION_MASTERY_GUIDE.pdf` (9 pages) & `.md`
- **Manual #2 (Homelab & Enterprise Systems Blueprint, 58 Components, 47 Architectures):**
  - `docs/manuals/HOME_LAB_SYSTEM_ARCHITECTURE_BLUEPRINT.pdf` (5 pages) & `.md`

## 2. Core Mastery Frameworks (`docs/`)
- **`docs/PRINCIPAL_FRAMEWORKS.md`** — 10 Universal System Archetypes (+ WebRTC Voice AI + VM/Container/MicroVM), Full 12-Chapter DDIA Audit, 5 Principal Thinking Frameworks, Enterprise Architecture Frameworks (C4, Well-Architected, Distributed Pattern Kit, Fitness Functions), Google SRE Mastery (SLI/SLO/Error Budgets, Golden Signals/RED/USE, Burn-Rate Alerting, Toil, ICS), 5-Layer QA & DR Standard, Build-in-Public Brand Engine, and 6 Additive Modular Packs.
- **`docs/FAILURE_MODES_AND_PERFORMANCE.md`** — Brendan Gregg's 5 Scientific Performance Models (USE, RED, TSA, On-CPU vs Off-CPU, Pragmatic eBPF) + **40 Mapped Production Failures across 8 Domains (~96-98% real-world incident coverage)**.
- **`docs/PYTHON_AUTOMATION_AND_ORCHESTRATION.md`** — The 8 Universal Enterprise Automation Archetypes, 7 Iron Laws of Unbreakable Python Automation, and the Orchestration Selection Matrix (Cron vs Queues vs Airflow/Dagster vs Temporal vs GitOps/Terraform/Ansible).

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
