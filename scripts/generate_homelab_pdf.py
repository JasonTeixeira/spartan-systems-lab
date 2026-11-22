"""
Generate HOME_LAB_SYSTEM_ARCHITECTURE_BLUEPRINT.pdf with zero external dependencies.
Uses the same clean PDF 1.4 engine as PYTHON_AND_SQL_PRODUCTION_MASTERY_GUIDE.pdf.
"""
import os
import sys

# Ensure we can reuse PDFBuilder from /Users/Sage/generate_pdf_manual.py
sys.path.insert(0, "/Users/Sage")
from generate_pdf_manual import PDFBuilder


class HomelabPDFBuilder(PDFBuilder):
    def _draw_running_header(self):
        y = self.height - 32.0
        cmd = [
            "q",
            "0.75 w 0.88 0.91 0.94 RG",
            f"{self.margin_x:.2f} {y:.2f} m {self.width - self.margin_x:.2f} {y:.2f} l S",
            "0.40 0.45 0.52 rg",
            f"BT /F2 7 Tf {self.margin_x:.2f} {y + 4:.2f} Td (HOMELAB & ENTERPRISE SYSTEMS ARCHITECTURE BLUEPRINT) Tj ET",
            f"BT /F1 7 Tf {self.width - self.margin_x - 160:.2f} {y + 4:.2f} Td ({self.escape(self.current_section[:38])}) Tj ET",
            "Q",
        ]
        self.current_cmds.append("\n".join(cmd))
        self.cursor_y = self.height - self.margin_top - 10.0

    def _draw_running_footer(self):
        y = 34.0
        cmd = [
            "q",
            "0.75 w 0.88 0.91 0.94 RG",
            f"{self.margin_x:.2f} {y:.2f} m {self.width - self.margin_x:.2f} {y:.2f} l S",
            "0.40 0.45 0.52 rg",
            f"BT /F1 7.5 Tf {self.margin_x:.2f} {y - 12:.2f} Td (SPARTAN SYSTEMS LAB -- PRINCIPAL ARCHITECTURE & SRE MANUAL) Tj ET",
            f"BT /F2 7.5 Tf {self.width - self.margin_x - 70:.2f} {y - 12:.2f} Td (Page {self.page_num} of ##TOTAL_PAGES##) Tj ET",
            "Q",
        ]
        self.current_cmds.append("\n".join(cmd))


def build_homelab_pdf(out_paths):
    primary_path = out_paths[0]
    os.makedirs(os.path.dirname(primary_path), exist_ok=True)
    pdf = HomelabPDFBuilder(primary_path)

    # ------------------------------------------------------------------
    # TITLE BLOCK & OVERVIEW
    # ------------------------------------------------------------------
    pdf.add_title_block(
        title="MASTER HOMELAB & ENTERPRISE SYSTEMS BLUEPRINT",
        subtitle="The 0.01% CCIE-Caliber Systems, Cloud, Data, AI/MLOps & SRE Execution Manual",
        meta_dict={
            "PRIMITIVES": "16 Categories / 58 Components",
            "ARCHITECTURES": "47 Canonical System Blueprints",
            "HANDS-ON LABS": "6 Enterprise Labs + 2 Micro-Labs",
            "CHAOS DRILLS": "12 Severe Enterprise Outages",
        },
    )

    pdf.add_callout(
        "The 0.01% Principal Architect Principle",
        "A top-0.01% Principal Systems Architect does not chase transient framework churn. They master the immutable "
        "physics of computing: Linux kernel syscalls (epoll, sendfile), memory bus & VRAM bandwidth, CPU cache-line "
        "alignment, TCP/IP wire flows, SQL query planners, and distributed consensus math.",
        callout_type="unlock",
    )

    pdf.add_heading_1("1. THE UNIFIED ARCHITECTURE STACK & 4-TIER PROGRESSION", section_tag="1. MASTER FRAMEWORK")
    pdf.add_table(
        headers=["Layer / Tier", "Scope", "Core Technologies & Physical Primitives"],
        rows=[
            ["Layer 5: Governance", "Business & FinOps", "Unit economics ($/req, $/1M tokens), SLOs/SLIs, Living ADRs, Compliance."],
            ["Layer 4: AI & Data", "Intelligence & Analytics", "vLLM/Ollama, Qdrant/pgvector, Iceberg Lakehouse, Redpanda/Kafka, ClickHouse, RAG."],
            ["Layer 3: Orchestration", "Distributed Runtime", "Kubernetes (Kind/k3s), Raft/etcd, Temporal durable workflows, Multi-Region sync."],
            ["Layer 2: Network/Mesh", "East-West & Edge", "TCP/IP, DNS, TLS/mTLS, Nginx/Envoy, Cilium eBPF, Anycast BGP, NetworkPolicies."],
            ["Layer 1: OS & Hardware", "Kernel & Silicon", "Linux syscalls (epoll, io_uring, sendfile), Page Cache, cgroups, NVMe IOPS, GPU HBM."],
        ],
        col_widths=[105, 110, 301],
    )

    pdf.add_bullet("Tier 1 - Primitives & Mechanics (90%):", "Linux, Python, SQL, DSA, Docker, and the 22 repeating daily operational tasks.")
    pdf.add_bullet("Tier 2 - Classic Distributed Systems (95%):", "29 classic architectural shapes (Alex Xu Vol 1 & 2), caching topologies, sharding, and queues.")
    pdf.add_bullet("Tier 3 - Full-Stack Enterprise Labs (98%):", "Production streaming FinOps, hybrid RAG/MLOps, zero-trust security, and zero-downtime migrations.")
    pdf.add_bullet("Tier 4 - Deep Systems & CCIE Forensics (0.01%):", "LSM-tree & Raft from scratch, zero-copy socket I/O, GPU roofline profiling, and blind chaos drills.")

    # ------------------------------------------------------------------
    # SECTION 2: PERIODIC TABLE OF SYSTEM DESIGN (58 PRIMITIVES)
    # ------------------------------------------------------------------
    pdf.add_heading_1("2. PERIODIC TABLE OF SYSTEM DESIGN (16 CATEGORIES / 58 PRIMITIVES)", section_tag="2. 58 PRIMITIVES")
    pdf.add_paragraph(
        "Every enterprise platform, cloud reference architecture, and AI system is built by wiring together a subset "
        "of these 58 building blocks across 16 architectural categories:"
    )

    pdf.add_table(
        headers=["Category", "Components (58 Total)"],
        rows=[
            ["1. Edge & Traffic (6)", "01 Anycast BGP, 02 Geo-DNS, 03 Global CDN, 04 WAF/DDoS, 05 L4/L7 Load Balancer, 06 API Gateway"],
            ["2. Compute Runtimes (5)", "07 Stateless APIs, 08 K8s Containers, 09 Serverless FaaS, 10 Async Workers, 11 MicroVM Sandbox"],
            ["3. Storage & DBs (7)", "12 Relational OLTP, 13 Key-Value, 14 Document/Wide, 15 Columnar OLAP, 16 Time-Series, 17 Graph, 18 Object S3"],
            ["4. Caching & Pools (4)", "19 Dist. RAM Cache (Redis), 20 In-Process LRU, 21 DB Conn Poolers (PgBouncer), 22 Semantic Vector Cache"],
            ["5. Messaging/Queues (4)", "23 Message Queues (SQS), 24 Commit Logs (Kafka/Redpanda), 25 Pub/Sub Fanout, 26 Dead-Letter Queues"],
            ["6. Search & Geo (3)", "27 Full-Text BM25, 28 Vector DB/HNSW (Qdrant/pgvector), 29 Geospatial H3/S2/Geohash"],
            ["7. Real-Time Sync (3)", "30 WebSockets/SSE, 31 WebRTC Relays, 32 CRDTs / Hybrid Logical Clocks (HLC)"],
            ["8. Consensus/Locks (4)", "33 Raft/Paxos Store (etcd), 34 Service Discovery, 35 Dist. Lock/Lease + Fencing, 36 Snowflake/UUIDv7"],
            ["9. Data Pipelines (3)", "37 DAG Schedulers (Dagster/Prefect), 38 Real-Time CDC (Debezium), 39 Stream/Batch Engines (Flink/DuckDB)"],
            ["10. AI / ML Infra (3)", "40 Model Serving (vLLM/Ollama), 41 AI Gateways/Routers (LiteLLM), 42 Feature/Eval Pipelines (MLflow/Phoenix)"],
            ["11. Zero-Trust Sec (3)", "43 OIDC/IdP (Keycloak), 44 RBAC/OPA IAM, 45 Vault/OpenBao KMS & Envelope Encryption"],
            ["12. Observability (3)", "46 Metrics/Logs (Prom/Grafana/Loki), 47 Dist. Tracing (OpenTelemetry), 48 FinOps Engines (Infracost/OpenCost)"],
            ["13. East-West Mesh (3)", "49 Service Mesh (Envoy/Istio), 50 eBPF Datapath (Cilium/Hubble/Tetragon), 51 Egress Gateway"],
            ["14. Multi-Region (3)", "52 Global ACID DB (Spanner/Cockroach), 53 WAN Sync/CRDT, 54 Geo-Fencing / Data Residency"],
            ["15. Progressive Eng (2)", "55 Dynamic Feature Flags, 56 Progressive Delivery & Chaos Engine (Argo Rollouts, Chaos Mesh)"],
            ["16. Hardware Physics (2)", "57 GPU Interconnects (NVLink/InfiniBand/RDMA), 58 Tiered Storage Media (RAM/NVMe/EBS/S3)"],
        ],
        col_widths=[122, 394],
    )

    pdf.add_heading_2("Critical Component Failure Modes & Capacity Heuristics")
    pdf.add_table(
        headers=["ID", "Component", "Primary Failure Mode at 10M Users", "Back-of-the-Envelope Capacity Rule"],
        rows=[
            ["05", "L4/L7 Load Balancer", "Ephemeral port exhaustion; conntrack table saturation.", "Max ~65k concurrent TCP conns per outbound IP."],
            ["12", "Relational OLTP (PG)", "Connection pool starvation; lock contention on writes.", "Sustained writes: ~5k-10k IOPS per disk volume."],
            ["15", "Columnar OLAP (CH)", "Too many small parts (unbatched inserts thrashing disk).", "Min batch: 10,000 rows or 1-sec write buffer."],
            ["19", "Dist. Cache (Redis)", "Cache stampede (thundering herd) on hot key expiry.", "Reserve 25% RAM overhead for BGSAVE fork."],
            ["24", "Commit Log (Kafka)", "Hot partition key causing consumer lag spikes.", "1 partition ~= 10 MB/s write, 20 MB/s read."],
            ["28", "Vector DB (Qdrant)", "RAM exhaustion (HNSW graph memory explosion).", "RAM = Vectors * (Dims*4 + M*8 bytes)."],
            ["33", "Consensus (etcd)", "Disk fsync latency jitter causing leader flip-flops.", "Require <10ms sustained p99 disk fsync."],
            ["40", "Model Serving (vLLM)", "KV-cache VRAM saturation stalling concurrent requests.", "VRAM = Weights + (Ctx * Layers * Concurrency)."],
            ["50", "eBPF (Cilium)", "Node BPF map exhaustion (bpf_map__create limit).", "Monitor BPF map memory & tail call metrics."],
        ],
        col_widths=[24, 102, 195, 195],
    )

    # ------------------------------------------------------------------
    # SECTION 3: THE 47 CANONICAL SYSTEM ARCHITECTURES
    # ------------------------------------------------------------------
    pdf.add_heading_1("3. THE 47 CANONICAL SYSTEM ARCHITECTURES CATALOG", section_tag="3. 47 ARCHITECTURES")
    pdf.add_bullet("Homelab Flagships & Micro-Labs (1-7):", "1. Event & FinOps Plane; 2. Enterprise AI & Agentic RAG; 3. Zero-Trust Workflow & Code Sandbox; 4. Multi-Region CRDT Sync; 5. Zero-Downtime Legacy Monolith Migration; 6. Pure-Code LSM-Tree & 3-Node Raft (Micro-Lab A); 7. Zero-Copy Socket Server & GPU Triton Profiler (Micro-Lab B).")
    pdf.add_bullet("Classic Distributed Systems (8-21, Alex Xu Vol 1):", "8. Rate Limiter; 9. Consistent Hashing Ring; 10. Snowflake Unique ID; 11. URL Shortener; 12. Web Crawler; 13. Notification System; 14. News Feed; 15. Real-Time Chat; 16. Video Transcoding (HLS/DASH); 17. Cloud Object Storage; 18. Search Autocomplete (Trie); 19. Proximity Service (Geohash/Quadtree); 20. Nearby Friends; 21. Google Maps & Routing.")
    pdf.add_bullet("Classic Distributed Systems (22-36, Alex Xu Vol 2):", "22. Distributed Message Queue; 23. Metrics Monitoring; 24. Ad Click Aggregation; 25. Hotel Reservation (Locking); 26. Payment Gateway; 27. Digital Wallet (Double-Entry Ledger); 28. Stock Exchange Matching Engine (LMAX); 29. Dynamo-Style KV Store; 30. Collaborative Editor (OT/CRDT); 31. Email Delivery; 32. Social Graph; 33. Multi-Tier CDN; 34. Distributed Task Scheduler; 35. Gaming Leaderboard; 36. Flash Sale / Virtual Queue.")
    pdf.add_bullet("Hyperscale & Frontier AI Infra (37-47):", "37. Multi-Node 3D-Parallel Model Training; 38. Multi-Tenant Iceberg/Flink Lakehouse & Feature Store; 39. Zero-Trust SPIFFE/SPIRE Service Mesh; 40. Global Multi-Raft NewSQL (Spanner/Cockroach); 41. 10M-Spans/s OTel Pipeline; 42. Firecracker MicroVM Build Farm; 43. Autonomous Multi-Agent Orchestrator; 44. Two-Tower + DLRM RecSys Funnel; 45. Post-Training RLHF/DPO Data Flywheel; 46. Global Edge Isolate Runtime; 47. Cell-Based Multi-Region DR.")

    # ------------------------------------------------------------------
    # SECTION 4: THE 6-LAB MASTER ENTERPRISE ARCHITECTURE
    # ------------------------------------------------------------------
    pdf.add_heading_1("4. THE 6-LAB MASTER ENTERPRISE ARCHITECTURE", section_tag="4. 6 ENTERPRISE LABS")
    pdf.add_paragraph(
        "Rather than building disconnected toy demos, wire all layers into one progressive monorepo where every "
        "component feeds the next, from declarative cloud/K8s foundations through streaming data, AI/MLOps, security, and chaos."
    )

    labs = [
        ("Lab 1: Sovereign Cloud, Multi-Tenancy & GitOps Foundation",
         "OpenTofu/Terraform, AWS Emulator/LocalStack, Kind (3-node K8s), ArgoCD, Cilium eBPF.",
         "Build a 100% declarative cloud + K8s foundation with zero manual kubectl edits and multi-tenant namespace isolation.",
         "Killer Test: Run destroy + apply + cluster rebuild; full platform must self-heal from Git in <7 minutes."),
        ("Lab 2: Autonomous Enterprise AI, RAG & MLOps Eval Engine",
         "Ollama/vLLM, Qdrant (hybrid dense + BM25), LiteLLM, Redis Semantic Cache, MLflow, Arize Phoenix / Promptfoo.",
         "Serve sub-2.5s multi-tenant RAG with RBAC filtering, semantic caching (>0.92 cosine), model routing, and CI/CD eval gates.",
         "Chaos Drill: Saturate inference with 200 concurrent requests + adversarial prompt injections; verify load shedding & zero tenant leaks."),
        ("Lab 3: Real-Time Data Lakehouse, Streaming & FinOps Control Plane",
         "Redpanda (Kafka), ClickHouse, MinIO (S3) + Apache Iceberg, DuckDB, Dagster/Prefect, PostgreSQL, Redis.",
         "Ingest 15k events/s, track real-time unit cost per tenant, enforce HTTP 429 budget circuit breakers, and tier cold data to S3.",
         "Chaos Drill: Inject 5k duplicate events/s during a 3-min ClickHouse outage; verify Redpanda buffering & penny-exact deduplicated billing."),
        ("Lab 4: Full-Stack App, Multi-Region Sync & Chaos SRE Cockpit",
         "FastAPI, PostgreSQL HA + PgBouncer, Redis, Nginx/Envoy, OpenTelemetry, Prometheus/Grafana, Chaos Mesh, k6.",
         "Operate a multi-tenant API under continuous chaos (20% packet drops, pod kills, DNS drops) while maintaining <300ms p99.",
         "Chaos Drill: Kill active DB node during checkout surge; verify PgBouncer failover, Outbox pattern (no double charges), and OTel traces."),
        ("Lab 5: Zero-Trust Security, Cryptographic Identity & Supply Chain",
         "OpenBao/Vault, Keycloak (OIDC), SPIFFE/SPIRE mTLS, Cosign, Trivy, Cilium Tetragon.",
         "Zero static secrets (15-min dynamic DB creds), short-lived mTLS SVIDs, signed-image admission gates, and runtime syscall kill-switches.",
         "Chaos Drill: Exec into a running pod and attempt metadata exfiltration or internal nmap; verify Tetragon SIGKILL & audit alert."),
        ("Lab 6: Distributed Consensus, Durable Workflows & Legacy Migration",
         "Temporal, Debezium CDC, Redpanda, Patroni HA Postgres, Envoy Proxy (shadow mirroring), Infracost.",
         "Migrate a 10M-row legacy monolith under 3k RPS live traffic via Strangler Fig, Debezium WAL CDC, and Expand-and-Contract.",
         "Chaos Drill: Kill the new microservice during 50% canary cutover; verify Envoy outlier detection falls back to legacy in <2s with 0 5xx."),
    ]
    for title, stack, obj, drill in labs:
        pdf.add_heading_2(title)
        pdf.add_bullet("Core Stack:", stack)
        pdf.add_bullet("Objective:", obj)
        pdf.add_bullet("Verification / Drill:", drill)

    # ------------------------------------------------------------------
    # SECTION 5: THE 2 WEEKEND MICRO-LABS
    # ------------------------------------------------------------------
    pdf.add_heading_1("5. THE 2 WEEKEND MICRO-LABS (DEEP SYSTEMS INTERNALS)", section_tag="5. MICRO-LABS")
    pdf.add_heading_2("Micro-Lab A: LSM-Tree Storage Engine & 3-Node Raft Consensus from Scratch")
    pdf.add_bullet("Part 1 - 300-Line LSM-Tree (Python/Go):", "Implement (1) append-only binary WAL for crash durability, (2) in-memory sorted MemTable, (3) 4MB flush to immutable SSTables with sparse index + Bloom filter, and (4) background two-way merge compaction removing tombstones/duplicates.")
    pdf.add_bullet("Part 2 - 3-Node Raft over Raw TCP:", "Implement randomized election timers (150-300ms), Term counters, RequestVote RPCs, AppendEntries majority quorum commits (floor(N/2)+1 = 2), and a split-brain leader partition + step-down reconciliation drill.")

    pdf.add_heading_2("Micro-Lab B: Zero-Copy Kernel I/O & GPU Triton Roofline Profiling")
    pdf.add_bullet("Part 1 - Zero-Copy Sockets (sendfile):", "Benchmark naive user-space f.read(4096) + sock.send() against os.sendfile() / splice with perf stat and strace -c; observe ~90% fewer context switches as Page Cache transfers directly to NIC DMA.")
    pdf.add_bullet("Part 2 - GPU Roofline & Triton (3-Hr Cloud GPU Sprint):", "Attainable TFLOPs = min(Peak Compute FLOPs, Memory Bandwidth GB/s * Operational Intensity). Profile PyTorch/vLLM with nsys/nvidia-smi and write a fused Triton Softmax kernel to observe SRAM vs HBM bandwidth savings.")

    # ------------------------------------------------------------------
    # SECTION 6: THE 12 SEVERE ENTERPRISE OUTAGES & WAR-ROOM DRILLS
    # ------------------------------------------------------------------
    pdf.add_heading_1("6. THE 12 SEVERE ENTERPRISE OUTAGES & CHAOS WAR-ROOM DRILLS", section_tag="6. 12 OUTAGES")
    pdf.add_table(
        headers=["#", "Outage Scenario", "Root Cause / Mechanism", "Triage Commands", "Permanent Fix"],
        rows=[
            ["01", "Cascading Retry Storm", "Un-jittered retries multiply load 20x during slowdown.", "ss -s; tcpdump -nn; RPS graph", "Exp. backoff + full jitter; load shedding."],
            ["02", "Silent MTU Blackhole", "Small pings pass; >1400B packets drop in overlay.", "ping -M do -s 1472; tcpdump", "PMTUD or clamp TCP MSS via iptables."],
            ["03", "DNS ndots:5 Meltdown", "K8s ndots:5 fires 5 search queries per external lookup.", "tcpdump port 53; hubble dns", "Set ndots:2; deploy NodeLocal DNSCache."],
            ["04", "DB Lock Stampede", "ALTER TABLE / unindexed FK blocks write threads.", "pg_stat_activity (wait=Lock)", "lock_timeout='2s'; Expand-and-Contract."],
            ["05", "conntrack Overflow", "Short-lived conn surge fills netfilter table; SYN drop.", "dmesg | grep nf_conntrack", "Raise nf_conntrack_max; HTTP keepalive."],
            ["06", "Poison Pill Queue", "Corrupt msg crashes consumer in CrashLoopBackOff.", "kubectl get pods -w; lag", "Dead-Letter Queue (3 strikes -> DLQ)."],
            ["07", "Inode Exhaustion", "Millions of 1KB files hit 100% inodes at 50% disk.", "df -i; find count per dir", "Cron cleanup; tar/archive to S3/MinIO."],
            ["08", "D-State I/O Freeze", "Hung disk/NFS traps PID in uninterruptible sleep.", "ps aux (D); /proc/PID/stack", "Fix storage path; hardware I/O watchdog."],
            ["09", "Cache Thundering Herd", "Hot key expires; 20k reqs slam Postgres at once.", "redis-cli --latency; pg_top", "SingleFlight mutex; XFetch / TTL jitter."],
            ["10", "Terraform State Lock", "Aborted CI run leaves state locked and drifted.", "tofu/terraform force-unlock", "Remote S3+lock backend; smaller stacks."],
            ["11", "GPU KV-Cache Deadlock", "Long prompts fill vLLM VRAM; queue stalls TTFT.", "nvidia-smi dmon; vllm metrics", "Chunked prefill; max context caps; HPA."],
            ["12", "Container Breakout", "Compromised pkg reads /etc/shadow or scans LAN.", "kubectl gadget exec; Tetragon", "Read-only rootfs; drop ALL caps; Tetragon."],
        ],
        col_widths=[20, 96, 138, 126, 136],
    )

    # ------------------------------------------------------------------
    # SECTION 7: TERMINAL COCKPIT & 60-SECOND LINUX SRE TRIAGE
    # ------------------------------------------------------------------
    pdf.add_heading_1("7. 60-SECOND LINUX SRE TRIAGE & TERMINAL COCKPIT", section_tag="7. 60-SEC TRIAGE")
    pdf.add_callout(
        "Brendan Gregg USE Method (Check on CPU, RAM, Disk, Network & Pools)",
        "1. Utilization (% time busy: iostat %util, mpstat %usr)  |  2. Saturation (queue waiting: vmstat r, TCP listen backlog)  |  "
        "3. Errors (explicit failure counts: netstat -s retransmits, dmesg OOM/disk errors).",
        callout_type="law",
    )

    pdf.add_code_block(
        [
            "1. uptime                  # Load avg vs CPU cores (rising or falling?)",
            "2. dmesg -T | tail -25     # Kernel ring buffer (OOM-killer? disk/NIC errors?)",
            "3. vmstat 1 5              # Run queue (r > cores = CPU starve; wa > 0 = I/O wait)",
            "4. mpstat -P ALL 1 3       # Per-core balance (single core pinned at 100%?)",
            "5. pidstat 1 3             # Exact PID burning CPU or disk I/O right now",
            "6. iostat -xz 1 3          # Disk saturation (%util > 90%? await > 20ms?)",
            "7. free -m                 # Available RAM vs Page Cache vs Swap",
            "8. sar -n DEV 1 3          # NIC throughput saturation / packet drops",
            "9. ss -s                   # Socket states (TIME_WAIT / CLOSE_WAIT / SYN_RECV)",
            "10. top / htop / btop      # Holistic view of threads and RSS memory",
        ],
        title="THE 60-SECOND LINUX TRIAGE LOOP (FIRST 10 COMMANDS ON ANY BROKEN BOX)",
    )

    pdf.add_code_block(
        [
            "# Attach syscall tracer with microsecond timestamps to a hung process:",
            "sudo strace -T -tt -p <PID> -f -e trace=network,file,desc",
            "# Capture live TCP/DNS wire traffic on an interface:",
            "sudo tcpdump -nn -i any 'port 5432 or port 53'",
            "# Live eBPF syscall & packet-drop snooping (on Linux kernel):",
            "sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { printf(\"%s %s\\n\", comm, str(args->filename)); }'",
            "sudo bpftrace -e 'kprobe:kfree_skb { printf(\"Dropped skb: %s\\n\", ksym(reg(\"ip\"))); }'",
        ],
        title="DEEP KERNEL & WIRE FORENSICS WEAPONS",
    )

    pdf.add_heading_2("Terminal TUI & Multi-Cloud Emulator Toolkit")
    pdf.add_bullet("Terminal Dashboards (TUIs):", "tmux (split cockpit), k9s (Kubernetes), lazydocker (Docker), pgcli (Postgres), btop/htop (system), lnav (structured logs), claws/taws (AWS TUI).")
    pdf.add_bullet("Local Emulators & CI/CD:", "aws/aws-emulator (official Rust AWS API emulator), kind (multi-node K8s), act (local GitHub Actions CI/CD), Azurite/localgcp (optional Azure/GCP).")
    pdf.add_bullet("Docs-as-Code & Discovery:", "Python diagrams, D2, Mermaid, InfraMap/Rover (Terraform graphs), Steampipe/Powerpipe (SQL over cloud APIs), and Git-tracked ADRs in docs/adr/.")

    # ------------------------------------------------------------------
    # SECTION 8: 12-WEEK SPARTAN EXECUTION ROADMAP & DEFINITION OF DONE
    # ------------------------------------------------------------------
    pdf.add_heading_1("8. 12-WEEK SPARTAN EXECUTION ROADMAP & DEFINITION OF DONE", section_tag="8. 12-WEEK ROADMAP")
    pdf.add_table(
        headers=["Weeks", "Active Lab & Focus", "Concrete Proof Artifact (GitHub Portfolio)"],
        rows=[
            ["Weeks 01-02", "Lab 1: Core Engine (Python, Postgres 16, PgBouncer, Redis, Nginx, Linux SRE Box, CI/act)", "10M-row benchmark README + EXPLAIN speedup + all 22 daily tasks + passing pytest/CI."],
            ["Weeks 03-04", "Lab 2: Cloud Data Pipelines (aws-emulator, Terraform, Redpanda, ClickHouse, MinIO, Grafana)", "Zero-loss 10k RPS ingestion + ClickHouse outage drill + real-time FinOps 429 breaker."],
            ["Weeks 05-07", "Lab 3: AI, Vector RAG & MLOps (Qdrant, Ollama, LiteLLM, MLflow, Phoenix, LightGBM/PyTorch)", "Hybrid RAG <2.5s + CI hallucination eval gate + anomaly model + 3-hr RunPod vLLM sprint."],
            ["Week 08", "Lab 4: Under-the-Hood Primitives (Pure Python/Go LSM-Tree, 3-Node Raft, Zero-Copy sendfile)", "Working WAL/SSTable/Bloom engine + Raft split-brain test + sendfile perf benchmark."],
            ["Weeks 09-12", "Lab 5: K8s, Zero-Trust & Blind Chaos Roulette (Kind, Cilium, ArgoCD, Vault, Chaos Mesh)", "Full GitOps rebuild <10 min + 12 blind outage post-mortems solved cold in <5 min each."],
        ],
        col_widths=[68, 224, 224],
    )

    pdf.add_callout(
        "The Spartan Daily Loop (75-90 Minutes/Day)",
        "15 min Cold Warmup (1 timed Python/DSA + 1 SQL drill against live Postgres, zero AI autocomplete)  ->  "
        "45-60 min Lab Combat (build or break 1 slice, blast with k6, trace with EXPLAIN/ss/strace/tcpdump)  ->  "
        "10 min Lock It In (clean Git commit + 10-line ADR/post-mortem + 5-min Staff-interview oral defense).",
        callout_type="unlock",
    )

    pdf.add_heading_2("The Final Definition of Done (0.01% Mastery)")
    pdf.add_bullet("1. Declarative Rebuild:", "Rebuild the entire multi-tenant platform from an empty machine via Git + Terraform + CI in under 10 minutes.")
    pdf.add_bullet("2. Blind Outage Triage:", "Survive a blind Chaos Roulette injection and isolate the exact root cause in under 5 minutes using only CLI/TUI tools (ss, dmesg, strace, tcpdump, EXPLAIN, k9s, Hubble).")
    pdf.add_bullet("3. Whiteboard & Trade-Off Defense:", "Sketch any of the 47 canonical architectures from memory, articulating exact data structures, wire protocols, failure modes, p99 SLOs, and dollar unit economics.")

    pdf.save()

    # Copy to any additional requested paths
    if len(out_paths) > 1:
        import shutil
        for extra in out_paths[1:]:
            os.makedirs(os.path.dirname(extra), exist_ok=True)
            shutil.copy2(primary_path, extra)
            print(f"Copied PDF to {extra}")


if __name__ == "__main__":
    build_homelab_pdf([
        "/Users/Sage/code/spartan-systems-lab/docs/manuals/HOME_LAB_SYSTEM_ARCHITECTURE_BLUEPRINT.pdf",
        "/Users/Sage/HOME_LAB_SYSTEM_ARCHITECTURE_BLUEPRINT.pdf",
    ])
