# How To Use This Lab (Day-0 Operator Manual & Review Engine)

> **One-page operational manual:** how to boot, practice, audit, patch, review, and reset your Spartan Systems Lab every single day.

---

## 1. Daily Session Workflow (Copy-Paste Start to Finish)

```bash
cd /Users/Sage/code/spartan-systems-lab

# 1. Run local cold Python/DSA drills (15 min, NO AI autocomplete!)
make drill-py

# 2. Boot Lab 1 (requires Docker Desktop running)
make up
make seed ROWS=250000

# 3. Open live visual dashboards
#    - Engineering SRE Ops (Grafana): http://localhost:3001  (admin / spartan)
#    - Executive BI (Metabase):       http://localhost:3000  (host=postgres, port=5432, db=spartan_lab, spartan/spartanpass)
#    - Edge API (Nginx -> FastAPI):   http://localhost:8080/healthz

# 4. Run live SQL & Linux triage X-rays
make pg-xray
make linux-triage
make sre-shell

# 5. Break it, diagnose cold, archive forensic proof, then reset clean
make chaos SCENARIO=lock-storm
make snapshot-incident NAME=lock-storm-rep1
make reset

# 6. Run full automated Code Review + Security + Supply-Chain Gate before every commit
make review
```

---

## 2. Automated Code Reviewer & "Principal Optimizer" Rubric

Every code change passes **two gates**:

### Gate 1: Automated Mechanical Reviewer (`make review`)
Runs locally in one command using tools already installed on your Mac:
1. **`ruff check .`** — Python lint, bugbear anti-patterns, import sorting, code hygiene.
2. **`mypy`** — Strict static type-checking across `app/`, `tools/`, and `tests/`.
3. **`shellcheck`** — Static analysis on every `.sh` Bash script (quoting, pipes, unbound vars).
4. **`gitleaks`** — Blocks leaked secrets/tokens/keys before they ever reach Git.
5. **`trivy fs .`** — Scans `uv.lock`, Dockerfiles, and IaC configs for CVEs and misconfigurations.
6. **`pytest tests/ -v`** — Automated unit/contract verification.

### Gate 2: The 5-Axis Principal Efficiency & Cost Review Rubric
After `make review` is green, check every solution against these 5 questions (and challenge your AI reviewer to grade you on all 5):
1. **Compute & Memory Efficiency:** Can $O(N^2)$ become $O(N)$? Can `.fetchall()` / `list` become `yield` streaming or vectorized SQL/Polars/Arrow?
2. **Database & I/O Cost:** Any N+1 loops, missing composite indexes, `SELECT *`, or unbatched writes?
3. **Operational Simplicity:** Is there a simpler design with fewer moving parts that still meets the SLO?
4. **FinOps (`$/month`):** Is this the computationally cheapest option (e.g., SQL/rules > LightGBM > small quantized model + semantic cache > frontier LLM)?
5. **Failure & Security Hardening:** Explicit timeouts, idempotency, parameterized SQL, non-root slim Docker image, and clean rollback?

---

## 3. Core Python Library Stack & Dependency Patching (`uv`)

Master these **~25 core libraries** (covers ~95% of Backend, Data, Automation & AI/ML engineering):

| Layer | Core Python Libraries |
| :--- | :--- |
| **Packaging, QA & Security** | `uv`, `ruff`, `mypy`, `pytest`, `hypothesis`, `bandit`, `pip-audit` |
| **Backend, APIs & Async** | `fastapi`, `pydantic` v2 + `pydantic-settings`, `uvicorn`, `httpx`, `tenacity`, `psycopg[binary,pool]`, `sqlalchemy` + `alembic`, `redis`, `grpcio`/`protobuf`, `prometheus-client`, `opentelemetry-sdk` |
| **Data & Pipelines** | `polars`, `duckdb`, `pyarrow`, `pandas` (legacy), `pyspark`, `dbt-core` |
| **AI, ML, Vectors & Agents** | `numpy`, `scipy`, `scikit-learn`, `lightgbm`, `torch` (PyTorch MPS/CUDA), `sentence-transformers`, `qdrant-client`, `litellm`, `mcp` (Model Context Protocol SDK), `mlflow`, `arize-phoenix` |
| **Ops & Business Automation** | `typer` + `rich`, `boto3`, `playwright`, `pdfplumber`, `openpyxl` |

### Dependency Patching & Safe Container Upgrade Workflow
```bash
# Check outdated / vulnerable deps and upgrade cleanly in uv.lock
uv lock --upgrade-package <pkg>
uv sync
trivy fs --scanners vuln,misconfig .
make review

# Rebuild slim non-root Docker image & scan the built image for OS/lib CVEs
docker compose -f lab-1-core-engine/docker-compose.yml build api
trivy image lab-1-core-engine-api
```

---

## 4. Audit Trail & Traceability (Documenting Everything You Do)

Every lab session leaves a clean, verifiable trail in Git:
- **Code & Infrastructure Changes:** Atomic Git commits on feature branches reviewed via `make review`.
- **Architecture Choices:** `docs/adr/NNN-title.md` + `docs/rfc/NNN-title.md`.
- **Real Outage Forensics:** `make snapshot-incident NAME=<slug>` archives container logs, `pg_stat_activity`, `pg_locks`, Linux `ss`/`vmstat`/`ip route`, and `git diff` into `docs/incidents/<timestamp>_<slug>/` before you run `make reset`.
- **Cost & Performance Proof:** `docs/benchmarks/` stores reproducible Before/After `k6` p99, `EXPLAIN ANALYZE`, and `tools/finops_calc.py` `$/month` receipts.
