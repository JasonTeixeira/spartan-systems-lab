# Deep Specialties: Production IaC, Clean Python & APIs, ML System Design, CISSP Security & Cloud Certs (+78 Units)

> **Closes the final 5 deep specialist tracks** so your system scales cleanly from 362 -> **440 Structured Building Blocks** while staying modular and open forever to future technologies.

---

## 1. Production Infrastructure as Code (IaC) Mastery (+14 Units)

Go far beyond basic `terraform apply`:
1. **Composable Versioned Modules:** Separate `modules/` (VPC, RDS, ECS, EKS, IAM) from environment roots (`envs/dev`, `envs/staging`, `envs/prod`).
2. **Remote State & Locking:** S3 backend + native lockfile / DynamoDB lock + state encryption + versioning (never commit `terraform.tfstate`!).
3. **State Surgery Without Downtime:** `terraform import` (adopt legacy click-ops resources), `moved {}` blocks (refactor modules with zero destroy/recreate), `terraform state mv/rm`.
4. **Continuous Drift Detection:** Scheduled CI `terraform plan -detailed-exitcode` alerting immediately when someone clicks in the cloud console.
5. **Policy-as-Code & Security Scanning:** `Checkov` / `Trivy config` / `OPA Conftest` blocking public S3 buckets, `0.0.0.0/0` SSH, or unencrypted EBS volumes in PRs.
6. **FinOps PR Gates:** `Infracost` commenting exact monthly `$/mo` delta directly on every Terraform PR.
7. **Immutable Golden Images (`Packer`):** Pre-bake hardened Ubuntu/Rocky AMIs with CIS benchmarks + Docker + OTel agent.
8. **Idempotent OS Config Management (`Ansible`):** Roles, playbooks, Vault-encrypted vars, `--check --diff` dry-runs across Ubuntu + Rocky/RHEL fleets.
9. **Kubernetes Packaging (`Helm` & `Kustomize`):** Environment overlays, schema-validated `values.yaml`, atomic `--rollback` upgrades.
10. **Kubernetes Control-Plane IaC (`Crossplane`):** Provision cloud DBs/buckets declaratively via K8s CRDs with continuous reconciliation.
11. **Ephemeral PR Environments:** Spin up full isolated staging stack per PR and auto-destroy on merge.
12. **Blast-Radius Layering:** Split state by change frequency (`01-network` -> `02-data` -> `03-compute` -> `04-app`) so an app bug never touches VPC/RDS state.
13. **Secret-Free IaC Pipelines:** GitHub Actions OIDC -> STS AssumeRole (zero static `AWS_ACCESS_KEY_ID` anywhere).
14. **Automated IaC Testing:** `terraform test` / `Terratest` proving real network reachability and security rules before merge.

---

## 2. Clean Python Software Craft & Production API Architecture (+18 Units)

### A. Clean Python & Software Architecture (*Cosmic Python / Fluent Python / Refactoring*)
1. **Hexagonal / Ports & Adapters:** Domain logic imports ZERO frameworks (`fastapi`, `psycopg`, `boto3`).
2. **Repository & Unit-of-Work Patterns:** Abstract persistence and atomic transaction boundaries cleanly so tests run fast in memory AND against real Postgres.
3. **Service Layer & Domain Events:** Keep routes thin (validate -> call service -> map response); decouple side-effects (emails, analytics, billing) via events/Outbox.
4. **Structural Typing (`typing.Protocol`) & Composition Over Inheritance:** Swap Redis/Postgres/Qdrant/LLM adapters cleanly without brittle class hierarchies.
5. **Immutable Value Objects & Domain Invariants:** `@dataclass(frozen=True)` + Pydantic v2 boundaries enforcing invariants at creation time.
6. **Explicit Exception Hierarchies:** Domain errors (`InsufficientFundsError`, `TenantQuotaExceeded`) mapped cleanly at the HTTP/gRPC edge—never leak raw SQL tracebacks.
7. **Deterministic Dependency Injection & Test Fakes:** Inject clocks, RNGs, DB pools, and HTTP clients so every race/retry/timeout is 100% unit-testable.
8. **Code Smell & Complexity Discipline:** Single responsibility, guard clauses (flat indentation), pure functions where possible, `ruff` + `mypy --strict`.

### B. API Architecture at Scale
9. **Resource-Oriented REST & OpenAPI 3.1 Contract-First Design:** Consistent nouns, HTTP verb semantics (`GET`/`POST`/`PUT`/`PATCH`/`DELETE`), generated SDKs/docs.
10. **RFC 7807 Problem Details Error Envelopes:** Machine-readable `type`, `title`, `status`, `detail`, `trace_id` across all services.
11. **Idempotency Headers (`Idempotency-Key`):** Safe retries on POST payments/orders/jobs with payload-hash mismatch detection (`409 Conflict`).
12. **Keyset (Cursor) Pagination:** Stable `O(log N)` pagination (`WHERE (ts, id) < (:ts, :id)`) with opaque base64 cursors.
13. **HTTP Caching & Concurrency Control:** `Cache-Control`, `ETag`, `If-None-Match` (`304 Not Modified`), `If-Match` optimistic locking (`412 Precondition Failed`).
14. **Rate-Limiting & Backpressure Headers:** Standard `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After` on `429 Too Many Requests`.
15. **Non-Breaking API Versioning & Deprecation:** Additive expansion, URI/header versioning, `Deprecation` + `Sunset` headers.
16. **gRPC & Protobuf at Scale:** Strict `.proto` field numbering, bidirectional streaming, **deadline/cancellation propagation** across microservice hops.
17. **GraphQL + N+1 DataLoader & Query Depth/Cost Limiting:** Prevent malicious nested queries from DDoSing Postgres.
18. **Production Outbound Webhooks:** HMAC-SHA256 signature + timestamp replay window (`5 min`), async worker delivery, exponential backoff + DLQ + webhook replay UI.

---

## 3. End-to-End ML System Design Mastery (+15 Units)

### The 7-Step ML System Design Framework (*Chip Huyen / Alex Xu ML*)
1. **Business Goal -> ML Framing:** Translate revenue/churn/latency KPI into exact ML task (binary classification, regression, pairwise/listwise ranking, retrieval, contextual bandits).
2. **Offline vs. Online Metrics Alignment:** Pair offline proxies (PR-AUC, LogLoss, NDCG@K, Calibration ECE, RMSE) with online business KPIs (CTR, conversion, revenue/user, guardrails).
3. **Data Strategy & Leakage Prevention:** Labeling pipelines, class imbalance handling, strict **time-based train/val/test splits** (never random split time-series!), and **point-in-time `ASOF JOIN`**.
4. **Feature Engineering & Feature Store:** Offline (Parquet/Iceberg) vs Online (Redis/DynamoDB) parity to eliminate train-serve skew.
5. **Iterative Modeling Ladder:** Heuristic baseline -> `LightGBM`/`XGBoost` tabular baseline -> Deep Neural Net (`Two-Tower`, `DLRM`, `Transformer`) only if lift justifies serving latency/cost.
6. **Serving Architecture & Latency Budget:** Batch pre-compute vs Online real-time (`<50ms`), ONNX/TensorRT optimization, multi-stage funnel (Candidate Gen -> Light Rank -> Heavy Rank -> Re-Rank business rules).
7. **Online Rollout, Feedback Loops & Drift:** Shadow deploy -> A/B test (sample-size power + p-value + guardrail metrics) -> continuous PSI/KL feature drift & concept drift retraining.

### The 8 Canonical ML Systems (Know All 8 Cold)
8. **Hyperscale Recommendation Funnel** (YouTube / TikTok / Amazon: Two-Tower ANN + DLRM + Diversity Re-rank)
9. **Search & Ad Ranking (CTR/CVR)** (Query understanding + BM25/Dense retrieval + calibrated pCTR * Bid)
10. **Real-Time Fraud & Anomaly Detection** (Extreme class imbalance, streaming velocity features in Redis/Flink, precision-recall trade-off, `<50ms` SLA)
11. **Demand Forecasting & Supply-Demand Matching** (Uber/DoorDash: Geospatial H3 hexagons + temporal features + quantile loss)
12. **Dynamic Pricing & Contextual Bandits** (Exploration vs exploitation, Thompson Sampling / UCB, revenue guardrails)
13. **Multimodal Content Moderation & Trust/Safety** (Text + Image/Video classifiers, confidence-threshold HITL escalation)
14. **Visual Search / Image Similarity & Embeddings** (CLIP/ViT embeddings + HNSW vector index + quantization)
15. **Enterprise GenAI / RAG / Agentic Systems** (Covered deeply in `docs/AI_ML_AND_LLM_MASTERY.md`)

---

## 4. Deep TCP/IP Networking & CISSP-Caliber Security Architecture (+19 Units)

### A. Networking & TCP/IP Physics (No Hardware Cisco Fluff — 100% Cloud + Linux Reality)
1. **CIDR & Subnetting Math Cold:** Instantly size `/16` (65,536 IPs), `/20` (4,096), `/24` (256, 251 usable in AWS), `/28` (16), non-overlapping VPC planning.
2. **Layer 2/3 Mechanics:** ARP, routing tables (longest-prefix match), NAT Gateway SNAT, Transit Gateway, VPC Peering (non-transitive!), PrivateLink/VPC Endpoints (zero internet egress).
3. **TCP Internals & Tuning:** 3-way handshake, FIN vs RST, `TIME_WAIT`/`CLOSE_WAIT`, flow control (rwnd), congestion control (CUBIC vs **BBR**), `TCP_NODELAY`, KeepAlives, MSS/MTU/PMTUD.
4. **UDP, QUIC/HTTP3 & WebRTC:** Zero head-of-line blocking, 0-RTT, ICE/STUN/TURN NAT traversal.
5. **DNS & Global Traffic Routing:** Recursive vs authoritative, A/AAAA/CNAME/ALIAS/TXT/SRV, TTL trade-offs, Route53 routing (Weighted, Latency, Failover, Geolocation), Anycast BGP.
6. **L4 vs L7 Load Balancing & Proxies:** DSR/NLB (IP/port passthrough, millions of RPS) vs ALB/Envoy/Nginx (TLS termination, path/host routing, retries, circuit breaking, WebSockets/gRPC).

### B. CISSP-Grade Cloud, App & AI Security Architecture
7. **Core Security Principles:** CIA Triad (Confidentiality, Integrity, Availability), Defense-in-Depth, Least Privilege, Separation of Duties, Zero Trust ("never trust, always verify").
8. **Applied Cryptography & PKI:** Symmetric (`AES-256-GCM`), Asymmetric (`RSA`/`ECDSA`/`Ed25519`), Hashing (`SHA-256`, `Argon2id` for passwords), `HMAC`, **KMS Envelope Encryption**, X.509 cert chains & TLS 1.3 handshake.
9. **IAM & Policy Evaluation Engine:** Explicit Deny > AWS Organizations SCP > Resource Policy > Permission Boundary > Session Policy > Identity Policy; OIDC/SAML 2.0 federation + STS short-lived tokens.
10. **Perimeter & Micro-Segmentation:** WAF (SQLi/XSS/bot), DDoS scrubbing, stateless NACLs vs stateful Security Groups, private DB subnets, strict egress filtering, Cilium L3/L4/L7 NetworkPolicies + mTLS.
11. **OWASP Top 10 & API Security Top 10:** BOLA/IDOR (object-level authz), SQL/Command Injection, SSRF (block `169.254.169.254` + enforce IMDSv2!), CSRF/XSS, Mass Assignment, Rate Limiting.
12. **OWASP LLM & Agentic Top 10:** Direct/indirect prompt injection, sensitive data/PII disclosure, cross-tenant RAG leaks, **excessive agency** (MCP tool least privilege + approval gates), supply-chain poisoned models (`safetensors` over `pickle`!).
13. **Threat Modeling (`STRIDE` + Attack Trees):** Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege — applied to every RFC before writing code.
14. **Software Supply Chain Security:** SBOMs, `Trivy` CVE gates, `Cosign` cryptographic image signing, distroless/non-root containers, read-only rootfs, drop `ALL` Linux capabilities.
15. **Secrets Lifecycle Management:** Zero secrets in Git (`gitleaks`), dynamic 15-min DB creds (`Vault`/`OpenBao`), automated key rotation, break-glass audit logs.
16. **Runtime Kernel Security:** `seccomp` syscall filtering, AppArmor/SELinux, **Cilium Tetragon** real-time syscall kill-switch.
17. **Incident Response Framework (NIST PICERL):** Preparation -> Identification -> Containment -> Eradication -> Recovery -> Lessons Learned (paired with `make snapshot-incident`).
18. **Data Privacy & Compliance Engineering:** GDPR Right-to-Delete across Postgres/S3/Qdrant, PII redaction (`Presidio`), immutable audit trails, SOC2 Type II / HIPAA / PCI-DSS / ISO 27001 controls.
19. **Shared Responsibility Model:** Exact security boundary between AWS/GCP/Azure (Security *of* the Cloud) vs. You (Security *in* the Cloud).
20. **NIST CSF 2.0 & MITRE ATT&CK Kill-Chain Defense:** Organize enterprise defense around **NIST CSF 2.0** (*Govern -> Identify -> Protect -> Detect -> Respond -> Recover*) and map **MITRE ATT&CK** attacker stages (*Initial Access -> Execution -> Privilege Escalation -> Credential Access -> Lateral Movement -> Exfiltration*) directly to concrete controls (WAF, non-root/drop-caps, Vault 15m creds, Cilium NetworkPolicies, Tetragon SIGKILL, egress firewall).
21. **Deep Applied Cryptography Primitives:** **AEAD** (`AES-256-GCM` / `ChaCha20-Poly1305` = confidentiality + tamper detection), **KDFs** (`HKDF` for key expansion, `Argon2id` for passwords), **Ed25519 / Cosign** digital signatures, **Merkle Trees** (Git commits, Apache Iceberg manifests, Raft logs, transparency logs), and **ECDHE Forward Secrecy** (compromised server key cannot decrypt past TLS 1.3 sessions).
22. **CISSP Risk Governance Delta (For Exam & C-Suite Risk Math):** Quantitative risk formula `ALE = SLE * ARO` (Annualized Loss Expectancy = Single Loss Expectancy * Annual Rate of Occurrence), Business Continuity Planning (BCP) vs Disaster Recovery (DRP), Recovery Time Objective (RTO) vs Recovery Point Objective (RPO).

---

## 4B. GPU Silicon Physics & Roofline Model (Vendor-Neutral Hardware Mastery)

Understanding **why NVIDIA H100/B200 chips dominate AI** transfers 1-to-1 to **Apple Silicon (MLX/Metal), AMD ROCm, and Google TPUs**:
1. **Compute-Bound Prefill vs. Memory-Bandwidth-Bound Decode (Roofline Model):**
   - `Attainable TFLOPs = min(Peak Tensor Core TFLOPs, HBM Bandwidth GB/s * Operational Intensity)`.
   - Reading a prompt (**prefill**) multiplies large matrices -> **Compute-bound**. Generating tokens one by one (**decode**) reads all model weights from VRAM per token -> **HBM Memory-Bandwidth bound** (H100 = `3.35 TB/s` vs CPU DDR5 `~100 GB/s`).
2. **SRAM vs. HBM & FlashAttention:** On-chip SRAM is ~10x faster than HBM VRAM but tiny (~50MB). FlashAttention tiles attention matrices inside SRAM to eliminate slow HBM round-trips.
3. **KV-Cache Paging & Continuous Batching (vLLM):** PagedAttention treats GPU VRAM like OS virtual memory pages, eliminating fragmentation so 1 GPU serves 10x–20x more concurrent users.
4. **NVLink & InfiniBand RDMA:** Direct GPU-to-GPU interconnect (`900 GB/s`) bypassing CPU/PCIe for Tensor & Pipeline Parallelism across multi-GPU clusters.

---

## 5. AWS Solutions Architect Pro (SAP-C02), AWS GenAI Pro & GCP Cert Delta (+12 Units)

Your 6 Labs + the 4 tracks above already cover **~85%-90%** of these flagship exams. Master these **12 Cloud-Vendor-Specific Delta Rules** to pass without breaking a sweat:
1. **Multi-Account Governance:** AWS Organizations, OUs, Service Control Policies (SCPs), AWS Control Tower, IAM Identity Center (SSO), Resource Access Manager (RAM).
2. **Hybrid & Multi-VPC Networking:** AWS Transit Gateway (hub-and-spoke), Direct Connect (DX) + Site-to-Site VPN failover, PrivateLink (Interface Endpoints) vs Gateway Endpoints (S3/DynamoDB), Global Accelerator (Anycast).
3. **High-Availability AWS Databases:** Aurora Global Database (`<1s` cross-region RPO), RDS Proxy (managed PgBouncer), DynamoDB Single-Table Design + GSIs/LSIs + DAX + Global Tables + Streams.
4. **Event-Driven & Serverless Choreography:** EventBridge (schema/rules), SNS -> SQS fanout + DLQ + FIFO deduplication, Step Functions (Standard vs Express workflows), Lambda concurrency (Reserved vs Provisioned).
5. **Large-Scale Cloud Migrations (7 Rs):** AWS DMS (homogenous/heterogenous CDC), Snowball/DataSync, Application Migration Service (MGN), Strangler Fig with CloudFront/ALB weighted target groups.
6. **Disaster Recovery Tiers (Cost vs RTO/RPO):** Backup & Restore (hours) -> Pilot Light (tens of mins) -> Warm Standby (mins) -> Multi-Site Active-Active (seconds, highest cost).
7. **AWS Storage Tiering & Lifecycle FinOps:** S3 Intelligent-Tiering / Standard-IA / Glacier Instant/Deep Archive, EBS `gp3` vs `io2` IOPS decoupling, EFS vs FSx.
8. **AWS GenAI & ML Managed Stack (GenAI Pro / ML Specialty):** Amazon Bedrock (Guardrails, Knowledge Bases, Agents, Provisioned Throughput vs On-Demand vs Batch), SageMaker (Feature Store, Pipelines, Clarify bias/drift, Multi-Model Endpoints, Async vs Real-Time Inference), OpenSearch Serverless Vector Engine.
9. **AWS Observability & Compliance Services:** CloudTrail (API audit), Config (drift/compliance rules), GuardDuty (threat detection), Security Hub, Macie (S3 PII discovery), VPC Flow Logs, X-Ray/OTel.
10. **Edge Security & Caching:** CloudFront (Origin Access Control OAC, Lambda@Edge vs CloudFront Functions), AWS WAF, AWS Shield Advanced, ACM TLS auto-renewal.
11. **Cost Governance (AWS FinOps):** Savings Plans / Reserved Instances vs Spot Fleet diversification, Cost Explorer, Budgets, Compute Optimizer, tagging enforcement via Tag Policies.
12. **GCP Cross-Walk (1-to-1 Translation):** VPC (global by default!) -> IAM/Org Policies -> Cloud Run / GKE Autopilot -> Cloud SQL / Spanner -> Pub/Sub -> BigQuery + GCS -> Vertex AI (Model Garden, Vector Search, Pipelines).
