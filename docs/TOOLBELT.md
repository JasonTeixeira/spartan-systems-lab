# Master Engineer Tool Belt (Backend, Data, AI/ML, Infra, Security & Frontend/Mobile)

> **The Handyman's Complete Toolkit:** Every CLI, TUI, GUI, Python library, Cloud/IaC tool, QA reviewer, and Frontend/Mobile framework in your stack—organized by task with exact 1-line commands. Designed for both quick terminal reference and direct querying by `spartan-mcp` (Step 2).

---

## 1. Linux, SRE Forensics & Network Wire Tools
| Tool | Layer | Primary Job | Go-To 1-Line Command |
| :--- | :--- | :--- | :--- |
| **`tmux`** | Terminal Cockpit | Split panes for live ops/logs/SQL | `tmux new -s ops` |
| **`btop` / `htop`** | CPU / RAM / Net TUI | Instant host resource overview | `btop` |
| **`ss` / `ip`** | Linux Sockets & Routes | Inspect listening ports, `TIME_WAIT`, CIDRs | `ss -s && ip route` |
| **`strace`** | Syscall Forensics | Trace hung process syscalls & timings | `sudo strace -T -tt -p <PID> -f` |
| **`tcpdump` / `tshark`** | Packet Capture | Inspect TCP handshakes, DNS, TLS, drops | `tcpdump -nn -i any 'port 5432 or port 53'` |
| **`dig` / `nc` / `curl`** | DNS & HTTP Wire | Verify DNS TTLs, ports, TLS/HTTP timings | `curl -v http://localhost:8080/healthz` |
| **`mitmproxy`** | HTTP/HTTPS Inspector | Interactive payload & header debugging | `mitmproxy --listen-port 8888` |
| **`lnav`** | Log Forensics TUI | SQL-queryable structured terminal log viewer | `lnav /var/log/syslog` |
| **`tools/linux-triage.sh`** | 60-Sec USE/TSA | Automated read-only Brendan Gregg triage | `make linux-triage` |

## 2. Python, Backend, APIs & Automated QA Reviewers
| Tool | Layer | Primary Job | Go-To 1-Line Command |
| :--- | :--- | :--- | :--- |
| **`uv`** | Packaging & Venv | Blazing-fast lockfiles, deps & patching | `uv sync && uv lock --upgrade-package <pkg>` |
| **`ruff`** | Linter & Formatter | Instant Python bugs, style & import checks | `uv run ruff check .` |
| **`mypy`** | Static Type Checker | Catch type & contract bugs before runtime | `uv run mypy lab-1-core-engine/app tools tests` |
| **`pytest` + `hypothesis`** | Unit & Fuzz Testing | Contract tests + automated property fuzzing | `uv run pytest tests/ -v` |
| **`FastAPI` + `Pydantic v2`** | API Core | Async REST/SSE/WebSockets + boundary validation | `uvicorn app.main:app --reload` |
| **`psycopg3` / `pgcli`** | PostgreSQL Driver/TUI | Connection pools, `COPY`, interactive SQL | `make pg-xray` |
| **`k6`** | Load & SLO Testing | Simulate 1k–10k RPS + enforce p99 gates | `k6 run lab-1-core-engine/scripts/load_k6.js` |

## 3. Data Engineering, Warehousing & Executive BI
| Tool | Layer | Primary Job | Go-To 1-Line Command |
| :--- | :--- | :--- | :--- |
| **`Polars` / `DuckDB` / `PyArrow`** | Local Analytical Core | Zero-copy Arrow/Parquet queries at laptop speed | `duckdb -c "SELECT * FROM 'data/*.parquet' LIMIT 10;"` |
| **`Apache Kafka / Redpanda`** | Event Backbone | Partitioned commit log, backpressure, DLQs | `rpk topic list` |
| **`ClickHouse`** | Columnar OLAP | Real-time sub-second aggregations on billions of rows | `clickhouse-client` |
| **`MinIO` + `Apache Iceberg`** | Open Lakehouse | Local S3 + ACID snapshots, time travel, compaction | `mc ls local/` |
| **`Airflow` / `Dagster` / `dbt`** | Orchestration & Modeling | DAG scheduling, backfills, Star Schema/OBT & WAP | `dbt build --select state:modified+` |
| **`Metabase` / `Apache Superset`** | Executive BI ("Money People") | Live CFO/VP KPI, Margin & FinOps Dashboards | Open `http://localhost:3000` |
| **`Grafana` + `Prometheus` + `OTel`** | Engineering Telemetry | RED metrics, p99 latency, traces, error burn rates | Open `http://localhost:3001` |

## 4. AI, ML, LLM Inference, RAG, Agents & Evals
| Tool | Layer | Primary Job | Go-To 1-Line Command |
| :--- | :--- | :--- | :--- |
| **`PyTorch` + `Hugging Face`** | Model & Training Core | `transformers`, `peft`/LoRA, `datasets`, `safetensors` | `uv run python -c "import torch; print(torch.backends.mps.is_available())"` |
| **`Ollama` / `mlx-lm` / `vLLM`** | LLM Inference Serving | Local Apple Silicon + CUDA PagedAttention serving | `ollama run qwen2.5:7b` |
| **`LiteLLM`** | AI Gateway & FinOps | Model routing, fallbacks, token cost tracking | `litellm --config config.yaml` |
| **`Qdrant` + `pgvector`** | Vector & Hybrid Search | Dense + BM25 + HNSW + `tenant_id` pre-filtering | Open `http://localhost:6333/dashboard` |
| **`LangGraph` + `MCP SDK`** | Agents & Tool Protocols | Stateful agent DAGs + schema-enforced MCP servers | `uv run python mcp-server/server.py` |
| **`MLflow` + `DVC` + `LightGBM`** | Classical ML & MLOps | Tabular ML, experiment registry, data versioning, drift | `mlflow ui` |
| **`Arize Phoenix` + `Promptfoo`** | AI/LLM Eval CI Gates | Faithfulness, groundedness, hallucination & red-team CI | `npx promptfoo eval` |

## 5. Cloud, IaC, Containers, Kubernetes & Visualizers
| Tool | Layer | Primary Job | Go-To 1-Line Command |
| :--- | :--- | :--- | :--- |
| **`Docker` + `lazydocker`** | Containers & TUI | Multi-stage slim builds, compose networks, live TUI | `make up && lazydocker` |
| **`Lima` (`limactl`)** | Local Linux VMs | Real Ubuntu / Rocky Linux VMs with systemd & eBPF | `limactl list` |
| **`Terraform` + `aws/aws-emulator`** | Cloud IaC & AWS Local | Declarative VPC/IAM/S3/SQS + `destroy && apply` | `terraform plan -detailed-exitcode` |
| **`Ansible`** | Server Config Mgmt | Idempotent Ubuntu/RHEL hardening, `nftables`, certs | `ansible-playbook site.yml --check --diff` |
| **`kind` + `kubectl` + `helm` + `k9s`** | Kubernetes & TUI | Multi-node local K8s + live cluster TUI | `k9s` |
| **`Cilium` (Hubble / Tetragon)** | eBPF Mesh & Runtime Sec | Live K8s packet/DNS drops + syscall kill-switch | `hubble observe --verdict DROPPED` |
| **`ArgoCD` + `act`** | GitOps & Local CI | Declarative K8s sync + run `.github/workflows` locally | `act -l` |
| **`d2` / `dot` / `inframap` / `Infracost`** | Diagrams & Cloud FinOps | Infra diagrams-as-code + exact PR `$/month` diffs | `infracost breakdown --path .` |

## 6. Security, Supply Chain & Automated Review Gates
| Tool | Layer | Primary Job | Go-To 1-Line Command |
| :--- | :--- | :--- | :--- |
| **`Trivy`** | CVE & IaC Scanner | Scan `uv.lock`, Docker images, Terraform, K8s YAML | `trivy fs --severity HIGH,CRITICAL .` |
| **`gitleaks`** | Secret Scanner | Block leaked API keys/tokens across Git history | `gitleaks detect --source . --redact` |
| **`shellcheck`** | Bash Static Analyzer | Catch quoting, pipe & unbound variable bugs | `shellcheck scripts/*.sh tools/*.sh` |
| **`OpenBao / Vault` + `Keycloak`** | Secrets & OIDC Identity | Dynamic 15-min DB creds, KMS envelope, SSO/RBAC | `vault status` |
| **`make review`** | Unified 6-Gate Reviewer | `ruff` + `mypy` + `pytest` + `shellcheck` + `gitleaks` + `trivy` | `make review` |

## 7. Frontend, React, React Native & Internal App Stack (Your Handyman Full-Stack Layer)
| Tool | Layer | Primary Job | Go-To 1-Line Command |
| :--- | :--- | :--- | :--- |
| **`React` + `Next.js` (App Router)** | Web App & Streaming UI | Fast SSE AI chat UIs, SSR/ISR, internal ops portals | `npx create-next-app@latest` |
| **`TypeScript` + `Tailwind CSS`** | Type-Safe UI & Styling | Strict API contract types + clean responsive layouts | `npm run typecheck` |
| **`React Native` + `Expo`** | iOS / Android Mobile Apps | Cross-platform mobile clients calling your FastAPI/AI APIs | `npx create-expo-app@latest` |
| **`TanStack Query` / `Zustand`** | Client & Server State | Caching, optimistic updates, WebSocket/SSE sync | `npm install @tanstack/react-query zustand` |
| **`Playwright`** | E2E Browser QA & RPA | Automated browser tests + legacy portal automation | `npx playwright test` |
| **`Storybook` + `Sage Design OS`** | Component Design System | Reusable accessible UI primitives & visual verification | `cd /Users/Sage/sage-design-os && npm run harness:verify` |
