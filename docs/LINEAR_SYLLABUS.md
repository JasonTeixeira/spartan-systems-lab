# The 12-Module Linear Compounding Spartan Syllabus

> **How To Use This Linearly (8-16 Hr/Day Spartan Mode — Repeatable Forever):**  
> Never jump randomly between 10 docs. Work strictly **M01 -> M12** in order. Every module runs **4 Parallel Daily Tracks** and ends with a **Boss Fight Gate**. On **Pass 2**, loop M01 -> M12 again in **Nightmare Mode** (new constraints, compound outages, tighter p99 SLOs, unseen Hard coding problems) until every primitive is native English.

---

## The 4 Parallel Daily Tracks (Run Every Single Day)

1. **Track A (45-60 min) — Cold Python & Unseen-Hard Coding (Constraint-First Method):** Solve timed problems cold (zero AI autocomplete), state the **loop invariant** out loud, analyze Big-O Time/Space, and run `pytest`.
2. **Track B (20-30 min) — Bash/Linux Pipes & SQL Speed:** Live `awk`/`sed`/`jq`/`ss`/`strace`/`tcpdump` + Postgres window functions, CTEs, `EXPLAIN (ANALYZE, BUFFERS)`.
3. **Track C (2-6 hrs) — Learn -> Immediately Build & Break in the Active Lab:** Read ONLY the 2-3 pages for the current module -> write the code/SQL/IaC yourself -> run `make review` -> stress & break it -> `make snapshot-incident` -> `make reset`.
4. **Track D (End of Module) — Module Boss Fight Gate:** Pass **(1) 1 unseen coding problem**, **(2) 1 live break-fix**, and **(3) 1 15-min whiteboard trade-off defense** before unlocking Module `N+1`.
5. **Track E (Weekly Friday, 45–60 min) — Executive, Content Factory, Consulting & Interleaved Chaos Rep (`LEADERSHIP_AND_EXEC_MASTERY.md`):** Write **1 Executive BLUF / PR-FAQ memo** (`$` & risk impact), record a **3-min spoken defense**, drill **1 STAR-L / DACI / MEDDPICC** scenario, run **1 Interleaved Chaos Roulette rep** from a prior module (15-min timer so you never forget M01–M03 while in M08–M11), and run the **25-min "1 Lab Rep -> 5 Assets" capture loop** (LinkedIn ArchOS carousel + YouTube teardown + 45s IG/Shorts clip + GitHub receipt).

> **Unified Decoupled Operating Contract (Spartan Lab <-> ArchOS):**  
> **ArchOS** (`http://127.0.0.1:5180/`) owns visual cognition (**178 standardized animated DS2 canvases** — 126 core + 52 Titanium Waves 1–4, with ~344 low-ROI encyclopedia stubs parked in Icebox), **159 canonical pattern skills / 560 concrete units across 9 disciplines** (with 2-stage **`Recalled` -> `Lab-Proven`** proof), and **FSRS spaced-repetition drills**. **Spartan Systems Lab** owns live execution on real/emulated infra (6 Core Labs, cold Python/SQL/Linux drills, 6-gate `make review`, 40 Failure Modes, 7-tool `spartan-mcp`, Executive/Consulting/Content playbooks). **2-Speed Daily Rule:** Fast Lane (`20–40 min/day`) = 15–40 ArchOS FSRS/Recall/Step-Walk reps on *already-learned* units; Deep Lane (`2–6 hrs/day`) = 1–3 *new* units built, stressed, and broken on metal until `Lab-Proven`.

---

## The 12 Sequential Compounding Modules

| Mod | Lab / Track | Concepts Learned -> Immediately Built, Stressed & Broken | Boss Fight Gate (Exit Proof) |
| :---: | :--- | :--- | :--- |
| **M01** | **Lab 1A: Python Core, Clean Code & Foundation DSA** | Hash Maps, Two Pointers, Sliding Window, Prefix Sums, Lazy Generators (`yield`), Pydantic v2, Cosmic Python (**Repository + Service Layer + DI**), `uv`/`ruff`/`mypy`/`pytest`. | Pass `make drill-py`, refactor `lab-1` into clean Domain/Service/Adapter layers, pass 6-gate `make review`. |
| **M02** | **Lab 1B: SQL Mastery, Postgres Internals & 10M Rows** | Window functions (`ROW_NUMBER`, `LAG`), CTEs, 3-valued NULLs, `EXPLAIN (ANALYZE, BUFFERS)`, Composite B-Tree, PgBouncer, **DDIA Lost Update & Write Skew**, Metabase Exec BI views. | Seed 1M-10M rows, drop query from seconds -> `<10ms`, reproduce & fix Write Skew live, verify Metabase KPIs. |
| **M03** | **Lab 1C: Linux Kernel, Bash Mastery, Grafana & Chaos #1** | `awk`/`sed`/`jq`/`xargs` forensics, Brendan Gregg USE/TSA/Off-CPU, `ss`/`strace`/`tcpdump`, Prometheus + Grafana 6-panel dashboard, `lock-storm` + `net-latency` + DR `backup`/`restore`/`reset`, plus optional live broken-VM reps on **`sadservers.com`** & **`labs.iximiuz.com`**. | Solve compound `lock-storm` + latency under `k6` cold, archive `make snapshot-incident`, pass DR restore checksum. |
| **M04** | **DSA Deep Surge + API Mastery + 3 Mini-System Katas** | Monotonic Stack/Queue, Heaps/Top-K, BFS/DFS/Topo Sort, Union-Find, Binary Search on Answer, Intervals, Backtracking, DP, Tries + **Full REST/OpenAPI 3.1/RFC 7807/Keyset/ETags/HMAC Webhooks** + build **URL Shortener, Rate Limiter, ACID Wallet** on Lab 1. | Solve 3 unseen Hard/Medium DSA problems cold under clock + benchmark all 3 Katas with `k6` on Grafana. |
| **M05** | **Lab 2: Deep TCP/IP, Linux VM, Security & Real Deploys** | Lima Ubuntu + Rocky/RHEL VM, CIDR subnetting math, `nftables` firewall, DNS, TLS 1.3/HTTPS + CDN caching (Nginx/Caddy), SSH Bastion, Protobuf/gRPC evolution, Ansible + zero-downtime Docker/`systemd` deploy. | Prove blocked private DB, capture & decode TLS/TCP handshake in `tcpdump`, execute zero-downtime deploy + rollback. |
| **M06** | **Lab 3A: Deep IaC Engineering & Core 12 AWS Services** | `aws/aws-emulator` + Terraform modules, remote state locking, `import`/`moved` state surgery, drift detection, `Checkov`/`Infracost`, VPC/CIDRs/SGs/IAM policy evaluation, S3/SQS/DynamoDB, `boto3` + `spartan-cli`. | Run `terraform destroy && apply` with zero manual touches + pass `Checkov` & `Infracost` PR check. |
| **M07** | **Lab 3B: Apache Data Platform, Lifecycle & FinOps** | 6-Stage Data Lifecycle, Kafka/Redpanda backpressure/DLQs, ClickHouse OLAP, MinIO + Apache Iceberg/Arrow/Parquet, Airflow + PySpark/DuckDB/dbt, Mailpit email, Apache Superset BI, all **12 Data Safeguards** (WAP, SCD2, `ASOF JOIN`). | Survive 3-min ClickHouse outage during 10k RPS + duplicate flood with penny-exact billing & FinOps `429` cap. |
| **M08** | **Lab 4A: Embeddings, Scaled Vector RAG & Inference** | Hugging Face (`transformers`/`sentence-transformers`), Qdrant hybrid dense+BM25+mandatory `tenant_id` pre-filter, Cross-Encoder reranking, Ollama/`mlx-lm` + LiteLLM, Redis Semantic Cache, 6 proven RAG patterns. | Hit `<2.5s` p95 RAG, prove 0% cross-tenant leakage on adversarial test, prove 60% token savings via cache + router. |
| **M09** | **Lab 4B: Agents, MCP, Voice AI, ML System Design & Evals** | Production MCP Server (schemas + approvals), LangGraph agents + OWASP LLM guardrails, WebRTC Voice AI, **7-Step ML Design + 8 ML Systems** (`mlsysbook.ai`), cold NumPy/PyTorch drills (`deep-ml.com`), LightGBM/PyTorch anomaly model + `Made-With-ML` Behavioral ML Tests + `DVC`/`MLflow`/Phoenix/DeepEval CI + 3-hr RunPod **vLLM/GPU** sprint. | Block a deliberately degraded prompt/model automatically in CI eval gate + tune vLLM KV-cache live on cloud GPU. |
| **M10** | **Lab 5: Pure-Code Internals (Zero Docker)** | 300-line **LSM-Tree** (WAL/MemTable/SSTable/Bloom/Compaction) + **3-Node Raft** over TCP + **Zero-Copy `sendfile`** + **`micrograd`** + **`minbpe`** + **Mini-GPT Attention + LoRA** from scratch on M3 Max PyTorch MPS (paired with **`deep-ml.com`** cold math/tensor drills & **`mlsysbook.ai`** hardware/serving chapters). | Pass Raft split-brain leader re-election test, prove ~90% fewer context switches in `sendfile`, train Mini-GPT + LoRA. |
| **M11** | **Lab 6: K8s, CISSP Zero-Trust, CDC Migration & Chaos** | 3-node `kind`, Cilium eBPF/Hubble/Tetragon, ArgoCD GitOps, OpenBao/Vault 15-min dynamic secrets, Keycloak OIDC, Postgres RLS, STRIDE threat model, Debezium CDC + Envoy Strangler Fig, **12 Blind Outages** (+ extra Linux/K8s break-fix reps on **`sadservers.com`** & **`labs.iximiuz.com`**) + ephemeral **Real-AWS Live-Fire**. | Rebuild cluster from Git `<10 min`, solve blind Chaos Roulette outages `<5 min` cold, survive 50% canary failure with 0 5xx. |
| **M12** | **Principal Capstone: Unseen Coding, Design, Certs & C-Suite** | Timed unseen Hard coding + 10-Archetype 45-min whiteboard drills + live anonymous Staff mock interviews (**`interviewing.io`**) + **AWS SAP-C02 / GenAI Pro Cert Delta** (final 2-week exam phrasing sprint on **Tutorials Dojo**) + Executive BLUF FinOps receipts + Build-in-Public teardowns + 2 upstream OSS PRs. | Deliver 3 reproducible `make bench` savings proofs, pass 3 mock 45-min Principal design loops, publish 3 terminal teardowns. |

---

## The Constraint-First Method (How to Crack Unseen Hard Coding Problems Cold)

1. **Read Input Constraint `N` FIRST (Before Guessing Any Algorithm):**
   - `N <= 20` -> Exponential / Backtracking / Bitmask DP ($O(2^N)$)
   - `N <= 500` -> $O(N^3)$ (Interval DP / Floyd-Warshall)
   - `N <= 5,000` -> $O(N^2)$ (2D DP / nested pairs)
   - `N <= 10^5` -> **Must be $O(N)$ or $O(N \log N)$** (Hash Map, Two Pointers, Sliding Window, Monotonic Stack/Queue, Heap, Binary Search on Answer, Sort + Greedy, Union-Find)
   - `N >= 10^9` -> **$O(\log N)$ or $O(1)$** (Binary Search / Math / Bitwise)
2. **Name the Loop Invariant Out Loud Before Typing:** *"At every step, window `[L, R]` satisfies X"* or *"Heap holds the K largest elements seen in `nums[0..i]`."*
3. **Trace 3 Edge Cases Before Running:** Empty/single element, all duplicates/negatives, maximum constraint / overflow.
4. **Narrate Time, Space & Production Trade-Offs:** Explain memory locality, streaming vs in-RAM, and how you'd scale it to 100M items (external merge sort / HyperLogLog / Bloom filter).

---

## ArchOS Visual Canvas Pairing (`http://127.0.0.1:5180/?diagram=<id>` -> Spartan Lab Modules)

Before starting any Module below, click its **Spartan Labs Infra** canvases (**12 dedicated live-infra & chaos deep-dive canvases** in `/Users/Sage/archos` under **`Spartan Labs Infra`**) + matching Failure Atlas, Migration, GPU/LLM, IaC & Security canvases (**178 standardized animated DS2 canvases total**) for 15 minutes of visual Recall Mode + Step-Walk, then switch to your terminal to build & break it on real metal:

- **M01 (Python, Clean Arch & APIs):** **`dgm_spartan-lab1-core-engine`**, `dgm_py-http-service-concurrency-models`, `dgm_py-memory-gc-and-profiling`, `dgm_py-packaging-typing-and-project-structure`, `dgm_request-lifecycle`, `dgm_stateless-web-tier`, `dgm_api-styles`, `dgm_idempotency-retries`
- **M02 (SQL, Postgres & 10M Rows):** **`dgm_spartan-lab1-core-engine`**, **`dgm_spartan-lab1-chaos-lock-storm`**, `dgm_sql-query-plans-and-indexing`, `dgm_db-migration-zero-downtime`, `dgm_fail-hot-partition-and-skew`, `dgm_transactions-and-isolation`, `dgm_db-scaling-ladder-v3`, `dgm_oltp-olap-split`, `dgm_serving-bi`
- **M03 (Linux, SRE & Grafana):** **`dgm_spartan-lab1-core-engine`**, **`dgm_spartan-lab1-chaos-lock-storm`**, `dgm_failure-taxonomy`, `dgm_fail-cascading-failure-and-retry-storm`, `dgm_fail-metastable-failure`, `dgm_fail-thundering-herd-and-stampede`, `dgm_fail-partial-and-gray-failure`, `dgm_observability-pillars`, `dgm_resilience-timeouts-breakers-bulkheads-shedding`, `dgm_capacity-estimation`
- **M04 (DSA, Scale APIs & 3 Katas):** **`dgm_spartan-lab1-core-engine`**, **`dgm_spartan-lab1-chaos-lock-storm`**, `dgm_api-deprecation-and-versioning`, `dgm_url-shortener`, `dgm_rate-limiter`, `dgm_api-gateway-design`, `dgm_digital-wallet`, `dgm_banking-ledger`
- **M05 (TCP/IP, Linux VM, TLS & Deploys):** **`dgm_spartan-lab2-linux-tcp-tls-deploy`**, **`dgm_spartan-lab2-zero-downtime-rollback`**, `dgm_architecture-evolution-path`, `dgm_monolith-decomposition`, `dgm_db-migration-zero-downtime`, `dgm_load-balancing-tiers`, `dgm_authn-authz-flow-v3`, `dgm_caching-layers`, `dgm_scale-from-zero`
- **M06 (IaC & Core 12 AWS):** **`dgm_spartan-lab3-iac-aws-apache-data`**, `dgm_iac-module-design-and-environment-promotion`, `dgm_iac-terraform-state-locking-drift`, `dgm_iac-policy-as-code-in-pipeline`, `dgm_datacenter-to-cloud`, `dgm_strangler-migration`, `dgm_sec-iam-policy-evaluation-least-privilege`, `dgm_sec-non-human-identity-and-secret-issuance`, `dgm_fail-correlated-failure-and-blast-radius`, `dgm_multi-tenant-saas`, `dgm_s3-object-storage`, `dgm_distributed-message-queue`
- **M07 (Apache Data, Lifecycle & FinOps):** **`dgm_spartan-lab3-iac-aws-apache-data`**, **`dgm_spartan-lab3-wap-clickhouse-outage`**, `dgm_warehouse-migration`, `dgm_fail-silent-data-corruption`, `dgm_fail-clock-skew-and-ordering`, `dgm_data-lifecycle-overview`, `dgm_cdc-to-lake`, `dgm_medallion-pipeline-v3`, `dgm_lakehouse-table-formats`, `dgm_dimensional-modeling`, `dgm_late-data-watermarks`, `dgm_data-quality-gates`, `dgm_retention-deletion-v3`
- **M08 (Embeddings, RAG & Inference):** **`dgm_spartan-lab4-ai-rag-mcp-evals`**, **`dgm_spartan-lab4-rag-acl-eval-gate`**, `dgm_llm-rag-retrieval-internals`, `dgm_llm-context-window-and-compaction`, `dgm_llm-llm-as-judge-calibration`, `dgm_sec-rag-poisoning-and-embedding-attacks`, `dgm_sec-indirect-injection-exfiltration-chain`, `dgm_rag-basic`, `dgm_rag-hybrid-rerank`, `dgm_rag-enterprise-acl`, `dgm_embedding-ingest-pipeline`, `dgm_llm-gateway-routing`, `dgm_llm-prefill-decode-and-batching`
- **M09 (Agents, MCP, ML, GPU & Evals):** **`dgm_spartan-lab4-ai-rag-mcp-evals`**, **`dgm_spartan-lab4-rag-acl-eval-gate`**, `dgm_agent-trajectory-and-tool-use-evals`, `dgm_agent-durable-runtime-checkpoint-resume`, `dgm_agent-multi-agent-failure-modes`, `dgm_mlops-training-serving-skew-casebook`, `dgm_mlops-gpu-serving-autoscaling-utilisation`, `dgm_linux-gpu-memory-hierarchy-and-roofline`, `dgm_net-gpu-cluster-fabric-nvlink-infiniband-nccl`, `dgm_llm-paged-kv-and-prefix-caching`, `dgm_llm-speculative-decoding-internals`, `dgm_llm-quantization-formats-and-kernels`, `dgm_llm-lora-and-adapter-merging`, `dgm_llm-mixed-precision-and-loss-scaling`, `dgm_llm-model-data-parallel-training`, `dgm_llm-preference-optimization`, `dgm_llm-moe-and-parallel-serving`, `dgm_legacy-decision-engine-to-ml`, `dgm_sec-agent-identity-and-least-privilege-tools`, `dgm_sec-agent-sandbox-code-execution`, `dgm_sec-ai-red-teaming-workflow`, `dgm_agent-platform`, `dgm_tool-gateway-mcp`
- **M10 (Pure-Code DB/Raft/LLM Internals):** **`dgm_spartan-lab5-internals-db-raft-llm`**, **`dgm_spartan-lab5-raft-splitbrain-compaction`**, `dgm_fail-split-brain-and-fencing`, `dgm_fail-clock-skew-and-ordering`, `dgm_kv-store-v3`, `dgm_consistent-hashing-ring`, `dgm_cap-pacelc`, `dgm_consistency-models`, `dgm_llm-attention-and-kv-cache`, `dgm_llm-constrained-decoding-and-structured-output`
- **M11 (K8s, Zero-Trust, CDC & Chaos):** **`dgm_spartan-lab6-k8s-cilium-zerotrust-cdc`**, **`dgm_spartan-lab6-ebpf-canary-strangler`**, `dgm_k8s-cluster-lifecycle-ha-and-upgrades`, `dgm_k8s-failure-triage-decision-tree`, `dgm_k8s-cni-services-and-network-policy`, `dgm_k8s-autoscaling-hpa-keda-node-provisioning`, `dgm_k8s-scheduler-requests-limits-qos`, `dgm_cdc-failure-backfill`, `dgm_ai-threat-model`, `dgm_sec-owasp-llm-top10-reference-architecture`
- **M12 (Principal Capstone & Whiteboards):** **`dgm_spartan-lab6-k8s-cilium-zerotrust-cdc`**, **`dgm_spartan-lab6-ebpf-canary-strangler`**, `dgm_interview-framework-45min`, `dgm_chat-system`, `dgm_video-streaming`, `dgm_news-feed-v3`, `dgm_payment-system`, `dgm_hotel-reservation`, `dgm_distributed-task-scheduler`

---

## The 10 "30-Year Veteran Battle Scars" (Never Taught in Courses)

1. **Hierarchical Timeouts (Inner < Outer):** Nginx `5s` > FastAPI `4s` > Postgres `statement_timeout 3s`. Reverse this and retries pile onto still-running dead DB queries.
2. **Never Couple Breaking DB Migrations With App Code in One Deploy:** Rolling deploys run v1 and v2 side-by-side. Always **Expand -> Deploy v2 -> Contract**.
3. **Throttle Mass Deletes & Backfills:** Never delete 50M rows in one tx; batch `5k-10k` rows with a `50ms` sleep to avoid lock storms & WAL replication lag.
4. **Queues Absorb Bursts — Never Permanent Overload:** If `in_rate > drain_rate` permanently, scale consumers, batch, or **shed load at the edge (`429`)**.
5. **Averages Always Lie — Check p99 & Skew By Tenant:** One mega-tenant with 100x rows will suffer `12s` latency while average latency looks like `40ms`.
6. **At-Least-Once + Idempotency + Forward-Only State Machines:** Beats mythical "exactly-once" network guarantees every time.
7. **Every Expensive Feature Ships With a Kill Switch & Fallback:** If OpenAI/Qdrant fails on Black Friday, degrade cleanly to cached/heuristic mode so checkout survives.
8. **Read the Literal Source of Truth First:** `EXPLAIN`, `pg_stat_activity`, `ss -tnp`, `curl -v`, `git log -n 5`, exact stack line 1 — never guess from memory.
9. **3-Second Production Safety Reflex:** Verify **context/env** -> run **dry-run / `SELECT COUNT(*)` / `plan`** -> know your **exact rollback command** before pressing Enter.
10. **Open & Extensible Forever:** Every time a new framework or vendor drops in 2027+, run Framework 5 (5 Physical Questions) and slot it into its exact Domain + Module without restarting from scratch.
