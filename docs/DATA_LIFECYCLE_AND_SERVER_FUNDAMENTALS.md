# Data Lifecycle, Locked-In Data Stacks, Server Archetypes & CI/CD Fundamentals

> **The missing bridge linking *Fundamentals of Data Engineering*, Database Modeling, Hardware Server Archetypes, and Self-Hosted CI/CD into your 6-Lab platform.**

---

## 1. The 6-Stage Data Lifecycle (The Horizontal Conveyor Belt)

Every piece of enterprise data travels through these 6 stages (with 3 undercurrents underneath all of them: **Governance/Security**, **DataOps/Observability**, and **Architecture/FinOps**):

| Stage | What Happens | Tools & Patterns | Failure Mode If Ignored |
| :--- | :--- | :--- | :--- |
| **1. Generation** | Created by app clicks, IoT, or external APIs. | Postgres OLTP (3NF), webhooks, payment gateways. | Upstream renames a column or changes timezone silently. |
| **2. Ingestion** | Extracted safely without crashing live prod DBs. | Batch ELT (`dlt`), Debezium CDC, Kafka/Redpanda, retries + schema contracts. | Rate limits (429), dropped events, prod DB overload. |
| **3. Storage** | Persisted durably in open formats. | S3/MinIO + Apache Iceberg + Parquet (**Medallion: Bronze -> Silver -> Gold**). | Small-file explosion, runaway S3 bills, unreplayable raw loss. |
| **4. Transformation** | Cleaned, deduplicated, PII-hashed, and modeled. | `dbt`/`SQLMesh`, DuckDB/Spark, 3NF -> Star Schema / OBT, Quarantine DLQ, **WAP**. | Duplicates, NULL poisoning, ML point-in-time leakage. |
| **5. Serving** | Exposed to humans, ML models, and live apps. | Metabase/Superset BI, Offline/Online Feature Stores, Reverse ETL, Redis/Qdrant. | Slow dashboards, stale RAG context, conflicting KPIs. |
| **6. Archival & Deletion** | Cold tiering and legal data purging. | S3 Glacier, Iceberg `VACUUM`, GDPR Right-to-Be-Forgotten purge jobs. | Paying for 7-year-old hot logs or failing privacy audits. |

---

## 2. The 4-Question Visual Database Decision Tree & 5 Locked-In Data Stacks

Never mix and match randomly. Once you know the workload, **Engine + Physical Layout + Storage Model + Schema Design** lock together automatically:

| Locked-In Stack | Workload | 1. Engine | 2. Physical Layout | 3. Storage Model | 4. Schema Design |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stack 1: Live App** | Single-row ACID writes/updates | OLTP (Postgres/MySQL) | Row-Oriented (Heap / B+ Tree) | Operational DB | **3NF (Normalized)** |
| **Stack 2: Raw & Clean History** | Data ingestion & replayability | Lakehouse (S3 + Iceberg) | JSON -> Parquet | **Medallion (Bronze -> Silver)** | Raw Nested -> Clean 3NF |
| **Stack 3: Executive BI** | Billions-row SQL aggregations | OLAP (ClickHouse/Snowflake/DuckDB) | Columnar (Parquet / Micro-parts) | Gold Data Mart | **Star Schema (`fct_` + `dim_`)** |
| **Stack 4: ML Training** | Wide flat feature matrices | DuckDB / Spark / Iceberg | Columnar (Parquet) | Offline Feature Store | **One Big Table (OBT)** |
| **Stack 5: Live App & AI (<10ms)** | Sub-10ms KV or semantic search | Redis / DynamoDB + Qdrant / `pgvector` | RAM Hash + HNSW Graph | Online Serving / Vector Store | Flat Key-Value + Vector[] + Metadata |

### The 5 Rapid-Fire Data Modeling Rules (Say These Out Loud in Interviews)
1. **Declare the Grain First:** *"One row in this table represents exactly [one completed line-item / one user-day]."* Never mix grains.
2. **Separate Facts from Dimensions (BI Gold):** Narrow numeric events in `fct_*`; descriptive context in `dim_*`.
3. **Preserve History with SCD Type 2:** Never overwrite `plan_tier` in `dim_users`—track `valid_from`, `valid_to`, and `is_current` so historical revenue reports stay accurate.
4. **Partition by Time, Cluster by Filter:** Partition by `event_date`; cluster/sort by high-cardinality join keys (`tenant_id`, `user_id`).
5. **Prevent ML Target Leakage with Point-in-Time `ASOF JOIN`:** Join events strictly to feature state known *prior* to `event_timestamp` (`events.ts >= features.updated_at`).

---

## 3. The 12 Data Engineering Production Safeguards (Local Laptop -> Enterprise Cloud)

| # | Safeguard | Local Laptop Implementation (Free) | Enterprise Cloud Implementation |
| :---: | :--- | :--- | :--- |
| **1** | **Idempotency** | `INSERT ... ON CONFLICT` / DuckDB `MERGE` / partition overwrite | Iceberg/Delta/Snowflake ACID `MERGE INTO` |
| **2** | **Watermarking** | `etl_watermarks` / `dlt` state + 2-hr lookback window | Spark/Flink RocksDB watermarks / CDC offsets |
| **3** | **Schema Contracts** | Pydantic v2 + `dbt` `contract: {enforced: true}` | Confluent Schema Registry (Protobuf/Avro) + Unity Catalog |
| **4** | **Quarantine (DLQ)** | Split bad rows to `_quarantine` table with `error_reason` | Kafka DLQ topic / AWS SQS DLQ + PagerDuty/Slack alert |
| **5** | **Backfill Design** | Explicit `execution_date` parameter + date partitions | Parallelized Airflow/Dagster partition backfills on S3 |
| **6** | **Point-in-Time / AI** | DuckDB `ASOF JOIN` + `embedding_model_v` / `chunk_v` metadata | Feast/Databricks Feature Store + versioned Qdrant namespaces |
| **7** | **Observability** | `pipeline_audit_log` + +/-3-sigma row-count dbt tests | OpenLineage + Datadog / Monte Carlo + freshness SLAs |
| **8** | **Storage & FinOps** | `EXPLAIN ANALYZE` + compact tiny files to 128-256MB Parquet | Iceberg `OPTIMIZE`/`VACUUM`, Z-Ordering, warehouse auto-suspend |
| **9** | **PII & Governance** | Salted SHA-256 hashing + Postgres RLS + `.env` / `gitleaks` | AWS KMS + Secrets Manager + dynamic column masking |
| **10** | **Write-Audit-Publish (WAP)** | Load `gold_staging` -> run full `dbt test` -> atomic `RENAME` | Iceberg Nessie branches (`audit` -> fast-forward `main`) / `SWAP WITH` |
| **11** | **API Resilience** | `tenacity` (exp backoff + jitter) + checkpointed pagination cursor | Step Functions / Kafka offset commit after durable write |
| **12** | **CI/CD & Slim Testing** | `make review` (`ruff`, `mypy`, `pytest`, `shellcheck`, `gitleaks`, `trivy`) | GitHub Actions Slim CI (`dbt build --select state:modified+`) |

---

## 4. Server Primitives, 5 Hardware Archetypes & Self-Hosted CI/CD

### What a Server Actually Is (4 Primitives)
A server is **just a continuous background process listening on a network port**:
1. **Compute & OS (Body):** Linux kernel + CPU/RAM/GPU.
2. **Process (Brain):** Long-running daemon (`uvicorn`, `nginx`, `postgres`, `vllm`) managed by `systemd` or container runtime.
3. **IP & Port (Door):** Street address + 65,535 ports, front-ended by DNS + Reverse Proxy (HTTPS/TLS on `443`).
4. **Storage (Memory):** Persistent volumes/disks so state survives restarts.

### The 5 Hardware Server Archetypes (80-90% Identical Linux DNA)
1. **General Compute:** Balanced CPU:RAM (1:4) — APIs, microservices, K8s workers.
2. **GPU / Accelerated:** Compute + PCIe/NVLink GPUs, CUDA drivers, massive HBM VRAM — LLM training/serving.
3. **Storage / DB:** High-IOPS NVMe/RAID + tuned I/O schedulers + huge page-cache RAM — Postgres, ClickHouse, Qdrant.
4. **Memory-Optimized:** 512GB–TB RAM — Redis, in-memory OLAP, zero-swap workloads.
5. **Bare-Metal Hypervisors:** Physical hosts (`Proxmox`/`KVM`/`QEMU`) + VLANs + IPMI/iDRAC out-of-band management.

### The 5 CI/CD Primitives & Cutting CI Bills 80-95%
- **5 Primitives:** `Event (on:)` -> `Runner (runs-on:)` -> `Job (jobs:)` -> `Step (steps:)` -> `Secrets & Artifacts`.
- **Golden Rules:** Never SSH + `git pull` to deploy (ship immutable Git-SHA-tagged Docker images); separate PR CI checks from `main` CD deploys; test locally with `act` before pushing.
- **Enterprise Cost Hack:** Keep GitHub UI + PR checks and attach **Self-Hosted GitHub Actions Runners** (or Kubernetes **Actions Runner Controller / ARC**) to run heavy Docker/AI builds on your own boxes for `$0/min` — or run **Forgejo + Forgejo Actions** (~300MB RAM) for 100% offline self-hosted Git + CI.
