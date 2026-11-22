# Principal Systems Thinking Frameworks & Visual Master Map

> **Zero Memorization. Pure First Principles.**  
> Every system in FAANG/NVIDIA/AI-lab interviews and Fortune 500 production reduces to the exact numbers below.

---

## 1. The Entire Universe By The Numbers

```text
+---------------------------------------------------------------------------------------------------+
|                           THE COMPLETE 0.1% UNIVERSE BY THE NUMBERS                               |
+---------------------------------------------------------------------------------------------------+
|   5   Database Storage Engines     -> Unlocks 100% of database logos on earth                     |
|   5   Principal Thinking Frameworks-> System Design, Debugging, Migration, FinOps, 48-Hr Mastery  |
|   4   Executive Proof Documents    -> RFC, ADR, Runbook, $/Perf Savings Receipt                   |
|   6   Stacked Homelabs             -> Hands-on mastery of ALL 10 Archetypes & ALL 12 DDIA Chaps   |
|  10   System Archetypes            -> Unlocks ALL 30+ Interview Systems (Netflix/Discord/Uber/AI) |
|  12   Severe Enterprise Outages    -> Covers ~90% of real production disasters                    |
|  14   DSA Coding Templates         -> Covers 95%+ of live coding interviews                       |
|  15   Physical Primitives          -> Linux, TCP/IP, Storage, Locks, Consensus, Crypto, GPU/Vec   |
|  22   Daily Operational Loops      -> 8 Python + 7 SQL + 7 Linux repeating tasks                  |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. How 6 Labs Unlock ALL 30+ Interview Systems (Netflix, Discord, Uber, Search, Stripe, LLM)

You do **not** build 30 separate apps. Every interview system in Alex Xu Vol 1 & 2, DDIA, and Frontier AI interviews is a combination of **10 Architectural Archetypes**, all built and broken inside your **6 Stacked Labs**:

| # | Universal System Archetype | Interview Systems It Unlocks | Exact Lab Where You Build & Break It |
| :--- | :--- | :--- | :--- |
| **1** | **High-Throughput Write & Metering** | Datadog, Metrics Monitor, Ad Click Aggregator, Stripe Metering, IoT Telemetry | **Lab 1 + Lab 3** (FastAPI + Kafka/Redpanda + ClickHouse + Redis) |
| **2** | **Strong-Consistency Financial / Booking Ledger** | Stripe Payments, Digital Wallet, Hotel Booking, Ticketmaster, Stock Exchange | **Lab 1** (ACID Postgres, MVCC/Isolation Anomalies, `SELECT FOR UPDATE`, Double-Entry Ledger, Outbox) |
| **3** | **Read-Heavy Feeds, Caching & Edge CDN** | Twitter/X Feed, Instagram, URL Shortener, Reddit, Multi-Tier CDN | **Lab 2 + Lab 3** (Nginx Edge/CDN headers, Redis Cache-Aside/SingleFlight, Read Replicas) |
| **4** | **Real-Time Bidirectional Sync, Voice & Presence** | **Discord**, Zoom/Voice AI Assistants (WebRTC STT->LLM->TTS), Slack, WhatsApp, Figma/Docs | **Lab 1 + Lab 4 + Lab 6** (WebSockets/SSE + Redis Pub/Sub + **WebRTC/LiveKit Voice AI <500ms** + CRDTs) |
| **5** | **Search, Autocomplete & Geospatial** | **Google Search**, Typeahead Autocomplete, **Uber / Nearby Friends**, Yelp, Google Maps | **Lab 1 + Lab 4** (Trie drill + PostGIS/Geohash drill + Qdrant Inverted BM25 + HNSW Vector) |
| **6** | **Large Blob / Media Pipeline & Transcoding DAG** | **Netflix / YouTube**, Dropbox, Google Drive, S3 Object Storage | **Lab 2 + Lab 3** (MinIO/S3 multipart upload + Airflow DAG workers + HTTP Range/CDN streaming) |
| **7** | **Distributed Coordination, Scheduling & Sandboxes** | Distributed Cron, GitHub Actions, Temporal, Rate Limiter, Snowflake IDs | **Lab 1 + Lab 5 + Lab 6** (Token Bucket, Raft Consensus, Leases/Fencing Tokens, Linux Namespaces/K8s) |
| **8** | **Batch & Streaming Data Lakehouse** | Uber Data Platform, Enterprise BI Warehouse, Feature Store | **Lab 3** (Apache Kafka + Iceberg + Arrow/Parquet + PySpark/DuckDB + Airflow + Watermarks) |
| **9** | **Production GenAI, Agents, MCP & Classical RecSys/ML** | **ChatGPT / Perplexity**, Enterprise Agents + MCP, Voice AI Agents, YouTube/TikTok Two-Tower RecSys, RLHF | **Lab 4** (MCP Server, Agent State Machines, Voice AI/WebRTC, Qdrant RAG, Ollama/vLLM, LiteLLM, MLflow + LightGBM/PyTorch, Phoenix Evals) |
| **10** | **Virtualization, Zero-Trust Security, Chaos & Brownfield** | Bare-Metal/VM vs Container vs MicroVM, Legacy Monolith Rescue, Multi-Region DR, Enterprise Cloud | **Lab 2 + Lab 6** (**Lima Linux VM** + `nftables`/DNS/TLS/Bastion, Vault/OIDC/mTLS, Debezium CDC + Strangler Fig, 12 Outages, Real AWS) |

---

## 3. Complete DDIA (Designing Data-Intensive Applications) 12-Chapter Audit

| DDIA Chapter | Core Physics & Gotchas | Where You Prove It Live |
| :--- | :--- | :--- |
| **Ch 1: Reliability, Scalability, Maintainability** | p50 vs p99 tail latency, SLOs, error budgets, load parameters | Lab 1 (`k6` + Nginx `$upstream_response_time`) |
| **Ch 2: Data Models** | Relational vs Document vs Graph, impedance mismatch | Lab 1 (3NF SQL), Lab 3 (Columnar), Lab 4 (Hybrid JSON/Vector) |
| **Ch 3: Storage & Retrieval** | B+ Trees vs LSM-Trees, SSTables, WAL, Bloom filters, OLTP vs OLAP | Lab 1 (`EXPLAIN`), Lab 3 (ClickHouse), **Lab 5 (Build LSM from scratch)** |
| **Ch 4: Encoding & Schema Evolution** | JSON vs **Protobuf/gRPC**, forward/backward compatibility | Lab 2/3 (gRPC/Protobuf service call + non-breaking schema evolution test) |
| **Ch 5: Replication** | Leader-follower lag, read-your-writes, multi-leader conflicts, quorum `W+R>N` | Lab 5 + Lab 6 (HA Postgres replica lag + failover drill) |
| **Ch 6: Partitioning / Sharding** | Hash vs range partitioning, hot keys, consistent hashing, secondary indexes | Lab 3 (Kafka partitions + ClickHouse) + Lab 6 (Tenant sharding) |
| **Ch 7: Transactions & Isolation Anomalies** | Dirty Read, Non-Repeatable Read, **Lost Update**, **Write Skew**, MVCC, 2PL, SSI | **Lab 1 (Live 2-terminal `psql` reproduction of Lost Update & Write Skew!)** |
| **Ch 8: Trouble with Distributed Systems** | Unreliable networks, clock drift (`time.monotonic()`), GC pauses, **fencing tokens** | Lab 1 (`tc netem`), Lab 5 (Raft), Lab 6 (Chaos Mesh) |
| **Ch 9: Consistency & Consensus** | Linearizability, CAP/PACELC, Total Order Broadcast, 2PC vs Raft | **Lab 5 (Build 3-Node Raft + split-brain drill from scratch)** |
| **Ch 10: Batch Processing** | Unix pipes, MapReduce/Spark, sort-merge joins, skew | Lab 3 (PySpark + DuckDB/Parquet batch pipelines) |
| **Ch 11: Stream Processing** | Event logs, Debezium CDC, event-time vs processing-time, watermarks, idempotency | Lab 3 (Redpanda + watermarks) + Lab 6 (Debezium CDC) |
| **Ch 12: Future of Data Systems** | Derived data, CQRS, end-to-end correctness & auditing | Lab 1 + Lab 3 (Outbox + reconciliation queries) |

---

## 4. The 5 Principal Thinking Frameworks (Mental OS)

### Framework 1: Requirements -> System Design (Any Interview or New Build)
1. **Business & Functional Requirements:** Exact 3-5 core workflows + hard business invariants (never double-bill, never leak cross-tenant data).
2. **Back-of-the-Envelope Physics Math:**
   - Read QPS, Write QPS (peak = `3x-5x` avg)
   - `Payload_Bytes * Writes/Day * 365 * 3` = 3-year Storage
   - Little's Law: `Concurrency = RPS * Avg_Latency_Seconds`
   - p99 Latency SLO, Consistency (ACID vs eventual), RPO/RTO, and `$/month` ceiling.
3. **Start Boring:** Draw the simplest spine (`Client -> DNS/TLS/LB -> Stateless API -> Postgres + Redis`).
4. **Evolve ONLY Where Math Forces You:** Add queues, caches, OLAP, vector DBs, or sharding *only* to break a proven mathematical bottleneck.
5. **Defend Failure Modes, Security & FinOps:** What breaks first at `10x`? How do we detect it in 60s? How do we roll back? What is the exact `$/1M requests` or `$/1M tokens`?

### Framework 2: The Detective / Debugging Loop (Any Unknown Broken System)
1. **What changed right before it broke?** (Deploy, migration, cert, config, traffic spike = ~80% of incidents.)
2. **Isolate Blast Radius:** 1 user, 1 tenant, 1 route, 1 node, or global?
3. **Binary-Search the Request Path:** `Client -> DNS/TLS -> Proxy -> App -> Pool -> DB/Queue/LLM`. Cut the search space in half every 60 seconds.
4. **Check USE on the Hot Layer:** Utilization, Saturation (queues waiting), Errors (`ss -s`, `vmstat`, `iostat`, `EXPLAIN`, `pg_stat_activity`, `strace`, `tcpdump`, structured logs/traces).
5. **Mitigate First, Capture Evidence, Fix Forever:** Stop bleeding (rollback/shed load) -> grab pcap/logs/EXPLAIN -> fix root cause + add automated regression test & alert.

### Framework 3: Legacy-to-Cloud Brownfield Migration
`Observe/Baseline -> Strangler Fig Proxy -> Debezium CDC + Shadow Mirroring -> Expand-and-Contract Schema -> Weighted Canary (1% -> 10% -> 50% -> 100%) with Auto-Rollback`.

### Framework 4: Principal FinOps & Trade-Off Defense (Beat Every Interview Gotcha)
Always answer trade-offs in 3 sentences:
1. *"The simple/cheap option is X (handles up to N RPS at $Y/mo)."*
2. *"The scalable option is Z (handles 100x load, costs $W/mo + operational overhead)."*
3. *"For this business constraint, I'd ship X today and trigger the migration to Z when metric M crosses threshold T."*

### Framework 5: Master Any Unfamiliar Technology in 48 Hours
Ask only 5 questions:
1. What physical layer does it own? (Compute, network, storage, queue, index, security?)
2. How does it store/move bytes? (B-Tree, LSM, RAM, append log, HTTP/gRPC/TCP?)
3. How does it scale and where does it break first? (CPU, RAM, IOPS, locks, network?)
4. How do I observe it live? (Metrics, logs, traces, CLI status command?)
5. How do I deploy, back up, and roll it back safely?

---

## 5. The 4 Executive Documents That Prove Your Value (How You Prove You Save Money)

1. **1-Page RFC (`docs/rfc/`):** Business KPIs, capacity math, 3 options with `$/month` comparison, failure modes, rollout/rollback plan.
2. **ADR (`docs/adr/`):** Permanent decision record + exact threshold to revisit.
3. **3:00 AM Runbook (`docs/runbooks/`):** Alert -> Exact CLI/SQL/Grafana check -> 60-second mitigation -> Root-cause checklist.
4. **Cost & Performance Proof Receipt (`docs/benchmarks/`):**
   > *"Before: 14.2s p99, 64 GB RAM, $4,800/mo -> After: 6ms p99, 1.2 GB RAM, $420/mo (**91% cost cut = $52,560/yr saved** — verified via k6 + EXPLAIN ANALYZE + Prometheus + Infracost)."*

---

## 6. "10x-50x Harder" Nightmare Mode (How Interviews Feel Like a Vacation)

Once a lab works on the happy path, run **Nightmare Mode** on it before moving on:
1. **No-Source-Code Rule:** During blind Chaos Roulette, forbid looking at app code for the first 10 minutes—isolate root cause strictly via `ss`, `tcpdump`, `strace`, `EXPLAIN`, `k9s`, Hubble, and Grafana.
2. **Compound Failures (Two Things Broken At Once):** Inject `lock-storm` AND `250ms packet loss` simultaneously under `k6` load.
3. **10M-Row Reality Check:** Never validate a SQL query or Python script on 100 rows—always test at `1M-10M` rows with capped container RAM (`256MB`) so naive code gets OOMKilled (`Exit 137`) on purpose.
4. **Live 2-Terminal DDIA Anomalies:** Reproduce a real **Lost Update** and **Write Skew** race condition live in PostgreSQL, watch money disappear, then prove your fix prevents it under concurrent load.
5. **Timed Cold Oral Defense:** Close all notes, draw the system on a blank sheet, calculate QPS/storage/cost math out loud, and survive 5 rapid-fire hostile Staff-interview failure probes.

---

## 7. Turning Homelab Proof Into Inbound Offers & Consulting Clients (Zero Fake Metrics)

Never fabricate company claims. Publish **100% reproducible, clone-and-verify engineering studies** from your labs:
1. **Reproducible Benchmark Repo:** Every optimization ships with `make bench` + Before/After `EXPLAIN ANALYZE` + `k6` p99 + Grafana screenshot + `Infracost` monthly cloud delta (e.g., *"10M rows: 14.2s -> 6ms p99; projected RDS/token spend cut 68%-91%"*).
2. **1 Technical Teardown Per Milestone (LinkedIn / X / Substack):** Diagram + real terminal proof + exact root cause + dollar impact + GitHub link.
3. **1 3-Minute Live Terminal Video (Loom / YouTube):** Trigger a live outage in `tmux` + `k9s` + Grafana + `tcpdump` and isolate/fix it cold in 3 minutes. Real engineers, recruiters, and CTOs recognize authentic mastery in 60 seconds.
4. **Upstream Open-Source PRs & Real Live Production Proof:** Once Labs 1-6 are complete, ship 1 live public HTTPS product/tool and land 2-3 real PRs in core repos (e.g., `vLLM`, `Qdrant`, `OpenTofu`, `FastAPI`) to stack undeniable real-world production proof.

