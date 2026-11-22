# Brendan Gregg Systems Performance & Complete Production Failure-Mode Field Manual

> **Why Fixing Broken Systems Is Where The Biggest Value Lives:**  
> Building greenfield apps is common. Walking into a bleeding 10M-user or AI/ML production system, isolating the exact physical bottleneck in 5 minutes, fixing it permanently, and proving the saved dollars to executives is rare top-0.1% leverage.

---

## 1. Brendan Gregg's 5 Scientific Performance Models (Zero Guessing)

Do not stare randomly at dashboards. Apply these 5 models from *Systems Performance*:

1. **USE Method (Hardware, OS & Resource Pools — CPU, RAM, Disk, NIC, DB Pools):**
   - Check **Utilization** (`% busy`), **Saturation** (`queue length waiting`), and **Errors** (`drops / OOM / retries`) on every resource.
2. **RED Method (Microservices & APIs) + Google 4 Golden Signals:**
   - **R**ate (RPS), **E**rrors (`4xx`/`5xx` %), **D**uration (p50 / p95 / **p99** tail latency) + **Saturation**.
3. **TSA (Thread State Analysis — Where Is Every Millisecond Actually Going?):**
   - Every thread in any language (Python, Go, Java, Postgres) is in ONE of 6 states:
     - **Executing (On-CPU)** -> Profile with CPU FlameGraph (`perf`, `py-spy`).
     - **Runnable (Waiting for CPU)** -> CPU starvation / cgroup throttling (`vmstat r`, `cpu.stat nr_throttled`).
     - **Swapping / Paging** -> Memory pressure (`vmstat si/so`, major page faults).
     - **Sleeping (Disk / Network / Lock I/O)** -> **Off-CPU FlameGraph**, `strace -T`, `pg_stat_activity`, `tcpdump`.
     - **Lock Wait (Mutex / DB Row Lock)** -> Lock contention (`futex`, `pg_locks`).
     - **Idle** -> Waiting for upstream work (check client/load balancer/queue).
4. **On-CPU vs. Off-CPU Analysis (The #1 Blind Spot of Most Engineers):**
   - If an API takes `4,000ms` but CPU is only `5%`, a CPU profiler will show **nothing**. Your code is **Off-CPU**—blocked waiting on a DB lock, DNS lookup, slow LLM API, disk `fsync`, or connection pool!
5. **Pragmatic eBPF (80/20 Business-Value Approach — Don't Get Lost Writing Kernel C):**
   - You do NOT need to write custom eBPF C programs to be top 0.1%. Master **running existing eBPF tools** to see inside the kernel with <1% overhead:
     - **Cilium Hubble:** Live Kubernetes packet drops, DNS errors, L7 HTTP/gRPC latency.
     - **Cilium Tetragon / Inspektor Gadget:** Live OOM kills, unexpected `exec` syscalls, container breakouts.
     - **BCC / `bpftrace` one-liners:** `execsnoop`, `opensnoop`, `tcpretrans`, `biolatency`, `runqlat` (scheduler latency).

---

## 2. Complete 7-Domain Production Failure Taxonomy (Every Major Break & Exact Fix)

Almost every production outage across Backend, Data, Cloud, Networking, Security, and AI/ML falls into one of these **7 Failure Domains**:

### Domain 1: CPU, Runtime & Concurrency Failures
| Failure Mode | User Symptom | Exact Proof Signal / Command | Permanent Engineering Fix |
| :--- | :--- | :--- | :--- |
| **K8s cgroups CPU Throttling** | Spiky p99 latency while avg CPU looks low (30%). | `/sys/fs/cgroup/cpu.stat` (`nr_throttled`, `throttled_usec`). | Remove/raise CPU limits (keep requests); right-size worker count. |
| **Python GIL / Event Loop Blocking** | Async FastAPI freezes for all users on 1 heavy request. | `py-spy top`, high event-loop lag, CPU pinned at 100% on 1 core. | Move CPU work to `ProcessPoolExecutor`; replace blocking drivers with async. |
| **Thread / Connection Pool Starvation** | `504 Gateway Timeout`, queues explode under modest traffic. | `pg_stat_activity` maxed; PgBouncer `cl_waiting > 0`; Little's Law exceeded. | Set strict timeouts; tune PgBouncer transaction pool; shed load early. |
| **Memory Leak & OOMKill (`Exit 137`)** | Pods crash-loop every few hours; sudden 502s. | `dmesg -T \| grep -i oom`; `kubectl describe pod` (`OOMKilled`); `tracemalloc`. | Stream with generators (`yield`); bound caches (LRU/TTL); fix retained refs. |

### Domain 2: Database, Storage & Transaction Failures
| Failure Mode | User Symptom | Exact Proof Signal / Command | Permanent Engineering Fix |
| :--- | :--- | :--- | :--- |
| **Missing Index / Stale Stats Seq Scan** | Sudden 10x-100x latency spike as table grows. | `EXPLAIN (ANALYZE, BUFFERS)` -> `Seq Scan`, huge `Buffers: shared read`. | Composite B-Tree index (`CONCURRENTLY`); run `ANALYZE`; avoid funcs on indexed cols. |
| **Lock Storm / DDL Migration Block** | Entire API freezes mid-deploy. | `pg_stat_activity` (`wait_event_type='Lock'`), `pg_locks` (`granted=f`). | Set `lock_timeout='2s'`; use Expand-and-Contract migrations. |
| **Lost Update / Write Skew (DDIA Ch 7)** | Silent money/inventory corruption under concurrency. | Reconciliation query mismatch; reproducible in 2 `psql` sessions. | `SELECT ... FOR UPDATE`, atomic `UPDATE ... WHERE`, or `SERIALIZABLE` + retry. |
| **Replication Lag / Read-Your-Writes Bug** | User updates profile/order, refreshes, sees old data. | `pg_stat_replication` (`replay_lag` bytes/seconds). | Route post-write reads to primary (session stickiness / LSN token). |
| **MVCC Vacuum Bloat / Disk / Inode Full** | Queries slow over weeks; `No space left on device` at 50% disk. | `df -h` AND `df -i`; `pg_stat_user_tables` (`n_dead_tup`). | Tune autovacuum; cron-clean temp files; partition & archive cold data to S3. |

### Domain 3: Networking, DNS, TLS & Edge Failures
| Failure Mode | User Symptom | Exact Proof Signal / Command | Permanent Engineering Fix |
| :--- | :--- | :--- | :--- |
| **DNS `ndots:5` Storm / Stale Resolver** | Intermittent 502s and 5s latency spikes. | `tcpdump -nn port 53`; `dig +trace`; Hubble DNS verdict. | Set `ndots:2`; deploy NodeLocal DNSCache; honor TTLs. |
| **TCP `TIME_WAIT` / Ephemeral Port / `conntrack` Exhaustion** | New connections fail randomly under high RPS. | `ss -s`; `dmesg \| grep nf_conntrack`; `cat /proc/sys/net/netfilter/nf_conntrack_count`. | Enable HTTP Keep-Alive connection pooling; raise `nf_conntrack_max`. |
| **Silent MTU Blackhole** | Health checks (`64B`) pass; real API payloads (`>1400B`) hang. | `ping -M do -s 1472 <IP>`; `tcpdump` retransmits on large frames. | Fix overlay MTU; clamp TCP MSS (`TCPMSS --clamp-mss-to-pmtu`). |
| **Expired TLS Cert / Broken Chain / SNI** | Sudden 100% outage for clients/webhooks. | `openssl s_client -connect host:443 -servername host`; `curl -v`. | Automate cert rotation (cert-manager/ACME) + 30-day expiry alert. |
| **VPC Route Table / NAT / SG Misconfig** | Private subnet times out silently (no RST). | `ip route`; `nc -zv`; VPC Flow Logs (`REJECT`); SG ingress/egress diff. | Least-privilege Terraform SG modules + automated reachability checks. |

### Domain 4: Caching, Queues & Distributed Systems Failures
| Failure Mode | User Symptom | Exact Proof Signal / Command | Permanent Engineering Fix |
| :--- | :--- | :--- | :--- |
| **Cascading Retry Storm (Self-DDoS)** | Minor 200ms slowdown turns into total outage. | Request rate jumps 10x-20x while errors spike; upstream saturated. | Exponential backoff + **Full Jitter**; retry budgets; circuit breaker + load shedding. |
| **Cache Stampede (Thundering Herd)** | Hot key expires -> DB CPU jumps to 100% instantly. | Redis miss spike + simultaneous identical SQL queries in `pg_stat_activity`. | SingleFlight mutex on miss; randomized TTL jitter; probabilistic early refresh. |
| **Poison Pill Message Loop** | Kafka/SQS consumer lag climbs infinitely; pods CrashLoop. | `kubectl get pods -w`; consumer group lag stuck on 1 offset. | Dead-Letter Queue (DLQ) after N retries + schema validation at ingress. |
| **Split-Brain / Zombie Worker Corruption** | Duplicate billing or overwritten state during partition. | Conflicting writes from old leader/worker after GC pause or net split. | Majority quorum (Raft) + **monotonic fencing tokens** checked by storage layer. |
| **Clock Skew Timeout Bug** | Negative durations or premature lease expirations. | NTP jump in logs; code using wall clock (`time.time()`). | Strictly use `time.monotonic()` for durations/timeouts; UTC `TIMESTAMPTZ` for data. |

### Domain 5: Data Pipelines & Analytics Failures
| Failure Mode | User Symptom | Exact Proof Signal / Command | Permanent Engineering Fix |
| :--- | :--- | :--- | :--- |
| **Silent Schema Drift / Dirty Nulls** | Executive BI dashboard shows `$0` or missing rows silently. | Row-count reconciliation drop; NULL spike; Pydantic/dbt contract failure. | Enforce data contracts at ingress; route corrupt records to DLQ; alert on freshness. |
| **Non-Idempotent Backfill / Duplicate Data** | Revenue doubled after pipeline retry. | Duplicate keys in fact table (`GROUP BY key HAVING COUNT(*) > 1`). | Atomic `INSERT ... ON CONFLICT` / Iceberg `MERGE`; watermark tables. |
| **Small-Files Problem (Iceberg/ClickHouse)** | OLAP queries crawl; S3 API bills explode. | Thousands of tiny `<1MB` Parquet files or ClickHouse parts. | Batch writes (`>=10k` rows); scheduled compaction jobs (Dagster/Airflow). |
| **Data Skew / OOM in Spark/SQL Joins** | 99% of job finishes in 10s, last 1% hangs for 2 hours. | Spark UI single straggler task; 1 hot key holds 80% of rows. | Salted keys / broadcast join for small dimensions; pre-aggregate before join. |

### Domain 6: Production AI, LLM, RAG, Agents & ML Failures
| Failure Mode | User Symptom | Exact Proof Signal / Command | Permanent Engineering Fix |
| :--- | :--- | :--- | :--- |
| **Silent Hallucination / Retrieval Degradation** | Users lose trust; AI invents facts after prompt/chunk tweak. | Automated golden-dataset eval drop (faithfulness < 0.95) in Phoenix/Promptfoo. | Hybrid dense + BM25 + cross-encoder reranker; block merges via CI eval gate. |
| **Cross-Tenant RAG Data Leakage** | Tenant A sees Tenant B's private documents in LLM answer. | Adversarial tenant-isolation test failure; missing metadata filter. | Mandatory `tenant_id` pre-filter in Qdrant/Postgres RLS (never post-filter). |
| **GPU KV-Cache Saturation / TTFT Explosion** | Time-To-First-Token spikes from `300ms` to `30s+`. | `nvidia-smi dmon`; `vllm:num_requests_waiting`; VRAM 99%. | Chunked prefill; FP8/AWQ quantization; semantic caching; max context caps. |
| **Runaway Agent Loop / Tool Abuse** | Single user request burns $50 in tokens or mutates prod DB. | OTel trace shows 30+ recursive tool steps; token cost alert spikes. | Max step/budget caps; deterministic state machine; approval gate on mutating MCP tools. |
| **Classical ML Train-Serve Skew & Drift** | Fraud/anomaly model accuracy silently decays over weeks. | Feature distribution PSI/KL drift in MLflow/Grafana; offline vs online gap. | Shared feature definitions; shadow deployment + continuous ground-truth evals. |

### Domain 7: Security, Deployments & FinOps Failures
| Failure Mode | User Symptom | Exact Proof Signal / Command | Permanent Engineering Fix |
| :--- | :--- | :--- | :--- |
| **Bad Deploy / Config Drift / State Lock** | 5xx surge seconds after merge; Terraform stuck locked. | Correlates 1:1 with commit SHA; `terraform plan` drift/lock error. | Automated canary rollback on 5xx; remote state locking; immutable containers. |
| **Credential Leak / Over-Permissive IAM** | Compromised container accesses S3/DB or metadata IP. | `gitleaks` alert; Tetragon exec/egress alert; CloudTrail anomaly. | OIDC keyless auth; Vault 15-min dynamic secrets; drop `ALL` Linux caps; IMDSv2. |
| **Silent Cloud / Token Bill Explosion** | Monthly AWS/LLM invoice jumps 4x unexpectedly. | FinOps BI dashboard (`v_exec_cost_drivers`), Infracost PR diff, NAT/egress spike. | Automated tenant `429` budget breakers; VPC endpoints (kill NAT egress); model routing + caching. |

### Domain 8: High-Frequency Cross-Cutting Operational Breaks (The Final ~10-12% -> ~96-98% Total Coverage)
| Failure Mode | User Symptom | Exact Proof Signal / Command | Permanent Engineering Fix |
| :--- | :--- | :--- | :--- |
| **Auth / Proxy / CORS / JWKS Drift** | Sudden 401/403s, redirect loops, or dropped cookies behind proxy. | `curl -v` (missing `X-Forwarded-Proto` / CORS headers); JWT decode (`exp`/`kid`). | Forward `X-Forwarded-*` headers cleanly; cache JWKS with background refresh; contract-test CORS. |
| **Missing Upstream Timeouts & Vendor `429`/`503`** | One slow vendor (OpenAI/Stripe/S3) hangs all app workers indefinitely. | `ss -tnp` (hundreds of `ESTABLISHED` sockets stalled); thread dump waiting in `httpx`/`requests`. | Enforce strict `connect_timeout` + `read_timeout` on EVERY outbound call + circuit breaker. |
| **`idle in transaction`, AB/BA Deadlocks & XID Wraparound** | Table bloat explodes; `ERROR: deadlock detected`; DB refuses writes near 2B XIDs. | `pg_stat_activity` (`state='idle in transaction'`); `age(datfrozenxid)` in `pg_database`. | Set `idle_in_transaction_session_timeout='30s'`; lock rows in deterministic ID order; monitor autovacuum XID age. |
| **K8s Probe Death Loops, Evictions & Slow HPA** | Pods restart endlessly during warmup or vanish under load. | `kubectl describe pod` (`Liveness probe failed`, `Evicted: ephemeral-storage`). | Separate `startupProbe`, `readinessProbe`, and gentle `livenessProbe`; set storage limits & pre-warm HPA. |
| **Rolling-Deploy Compat, DST Timezones & Float Drift** | Errors spike ONLY mid-deploy; billing off by 1 hr or `$0.01`. | 500s on old/new pods during rollout; float rounding diffs. | Enforce backward-compatible Expand-and-Contract schemas; strict UTC `TIMESTAMPTZ` & `Decimal`/`NUMERIC`. |
| **Overlapping Crons & Out-of-Order Webhooks** | Batch job runs twice simultaneously; `paid` event arrives before `created`. | Duplicate PIDs in `ps aux`; state machine rejects out-of-order event. | Distributed advisory lock (`pg_try_advisory_lock`/Redis lease) on every cron; idempotent state checks + upsert. |
| **Cloud Quotas & VPC `/24` IP Exhaustion** | K8s autoscaler fails to launch pods; AWS API throws `LimitExceeded`. | `kubectl describe rs` (`Insufficient IP`); AWS CloudTrail throttling; NAT port metrics. | Size VPC CIDRs (`/16` VPC, `/20` subnets); monitor quotas with alerts at 75%; request quota bumps proactively. |
| **Observability Self-Sabotage (High-Cardinality / Disk Full)** | Prometheus OOMs; Postgres crashes because debug logs filled `/` to 100%. | `df -h`; Prometheus TSDB head series spike (`prometheus_tsdb_head_series`). | Ban unbounded IDs (`user_id`, `request_id`) as metric labels; enforce log rotation + `INFO` default in prod. |

