# AI, ML, LLM Inference, RAG, Agents & Evals Mastery Blueprint (Lab 4 + Lab 5 AI Track)

> **Primary Specialty Playbook:** Everything required to design, build, evaluate, serve, secure, and optimize production GenAI, RAG, Agents/MCP, Inference, and Classical ML systems from first principles to Principal AI Architect level.

---

## 1. The Complete Open-Source AI & LLM Stack (What To Master & Why)

| Layer | Core Open-Source Tools | What You Actually Master Under the Hood |
| :--- | :--- | :--- |
| **Core Model & HF Ecosystem** | **PyTorch** (MPS/CUDA), **Hugging Face** (`transformers`, `datasets`, `tokenizers`, `peft`, `accelerate`, `safetensors`, `sentence-transformers`) | Loading open weights cleanly, BPE tokenization, fine-tuning (`LoRA`/`QLoRA`), memory-safe `safetensors`, batching & tensor shapes. |
| **Local & Production Inference** | **Ollama** + **`mlx-lm`** (Apple Silicon local), **vLLM** (CUDA prod), **LiteLLM** (AI Gateway) | Quantization (`GGUF`, `AWQ`, `FP8`), **PagedAttention**, **KV-cache VRAM math**, continuous batching, speculative decoding, **TTFT** vs **ITL**, dynamic model routing, token FinOps. |
| **Embeddings & Scaled Vector RAG** | **`sentence-transformers`**, **Qdrant** (hybrid dense + BM25), **`pgvector`** (HNSW), Cross-Encoder Rerankers | Bi-encoders vs cross-encoders, Matryoshka/int8 embeddings, Cosine/Dot/L2 math, **HNSW tuning** (`M`, `ef_construction`, `ef_search`), structure-aware & parent-child chunking, mandatory `tenant_id` pre-filtering. |
| **Agents, Workflows & Protocols** | **LangGraph** (stateful cyclic DAGs + checkpointers + HITL interrupts), **LangChain** (interoperability only), **MCP** (Model Context Protocol SDK), **Pydantic v2** | When to use **LangGraph** (stateful multi-step agents with persistence/replay/HITL) vs. clean **pure-Python `asyncio` + Pydantic + MCP** (zero wrapper bloat); strict tool schemas, step/budget caps, prompt-injection guardrails. |
| **AI & LLM Evals + Tracing** | **Arize Phoenix**, **Promptfoo**, **RAGAS**, **OpenTelemetry**, **MLflow**, **DVC** | Programmatic eval suites blocking bad merges in CI (no "vibe checking"!): retrieval metrics, faithfulness, hallucination rate, agent trajectory evals, behavioral ML tests, and drift monitoring. |
| **Classical ML & Voice AI** | **`scikit-learn`**, **`LightGBM`**, **PyTorch**, **LiveKit / WebRTC** (`STT -> LLM -> TTS`) | Tabular/ranking/anomaly models (knowing when **NOT** to use an LLM!), feature pipelines, point-in-time `ASOF JOIN`, and sub-500ms Voice AI pipelines with barge-in. |

---

## 2. Embeddings & Production RAG Mastery (The 6 Proven Patterns)

Skip 90% of gimmicky RAG demos. Master and benchmark these **6 production patterns** against a golden eval set:
1. **Structure-Aware & Parent-Child Chunking:** Preserve headings/tables/code boundaries; retrieve tiny child chunks for precision, pass larger parent context to the LLM.
2. **Hybrid Search (Dense Vectors + Sparse BM25) + Reciprocal Rank Fusion (RRF):** Dense vectors catch semantics ("car" <-> "automobile"); BM25 catches exact IDs, SKUs, error codes, and proper nouns.
3. **Two-Stage Retrieval + Cross-Encoder Reranking:** Fetch top-50 candidates fast with bi-encoder/BM25 -> score top-50 accurately with a cross-encoder -> send top-5 to the LLM.
4. **Mandatory Multi-Tenant Metadata Pre-Filtering:** Filter `tenant_id` & RBAC roles *inside* the vector index query (Qdrant payload index / Postgres RLS)—never post-filter after top-K retrieval.
5. **Query Transformation, Semantic Caching & Model Routing:** Rewrite ambiguous queries / HyDE when needed; intercept repeated queries in **Redis Semantic Cache** (`cosine > 0.92`, `<15ms`); route simple intents to cheap small models.
6. **Corrective / Self-Checking RAG (CRAG) & Inline Citations:** Verify retrieved context relevance before generating; return chunk-level citations or refuse cleanly ("I don't have sufficient evidence") when retrieval scores are low.

---

## 3. Complete AI, LLM & ML Evaluation Pyramid (CI/CD Quality Gates)

Never ship prompt, chunking, model, or retrieval changes without automated pass/fail gates:

1. **Retrieval Evals (Deterministic, Fast, `$0`):**
   - **Recall@K** (did the right chunk appear in top K?), **MRR** (Mean Reciprocal Rank), **NDCG@K** (ranking quality).
2. **Generation & RAG Evals (Golden QA Dataset + Calibrated LLM-as-a-Judge):**
   - **Faithfulness / Groundedness** (every claim supported by retrieved context; gate `>= 0.95`), **Context Precision**, **Answer Relevance**, **JSON Schema Adherence (100%)**, and **Refusal Accuracy** on unanswerable prompts.
3. **Agent & MCP Trajectory Evals:**
   - **Tool Selection Accuracy** (did it pick the right MCP tool with valid args?), **Step Efficiency** (within max step/token budget?), **Safety / Adversarial Red-Teaming** (prompt injection, PII leakage, unauthorized mutating tool calls blocked 100%).
4. **Inference Performance & FinOps Evals:**
   - **TTFT** (Time-To-First-Token), **ITL** (Inter-Token Latency), **Throughput (tokens/sec)** under concurrency, and **Cost per 1,000 queries (`$/1k`)**.
5. **Behavioral Classical ML Testing (from `Made-With-ML`):**
   - **Data Validation Tests** (no NaNs, valid ranges, schema contract), **Slice-Based Evals** (accuracy across every user/tenant segment), **Invariance Tests** (irrelevant change must not flip prediction), **Directional Expectation Tests** (stronger risk signal must raise risk score), and **Feature Drift (PSI/KL)** alerts.

---

## 4. Surgical Extraction Plan From the 6 Gold-Standard Open-Source Repos

Use these 6 repos as **surgical build references** inside Labs 4 & 5—do NOT binge notebooks passively:

| Repo | Target Lab | Exact Surgical Slice to Extract & Build |
| :--- | :--- | :--- |
| **`karpathy/nn-zero-to-hero`** | **Lab 5 (AI Internals)** | Build `micrograd` (autograd/backprop), `minbpe` (BPE tokenizer), and `nanoGPT` self-attention on M3 Max PyTorch MPS. |
| **`rasbt/LLMs-from-scratch`** | **Lab 5 (AI Internals)** | Build clean modular PyTorch Causal Multi-Head Attention (Ch 3), GPT Block + Weight Loading (Ch 4-5), Instruction Tuning (Ch 7), and **LoRA from scratch (Appendix E)**. |
| **`GokuMohandas/Made-With-ML`** | **Lab 4 (MLOps CI)** | Extract **Behavioral ML Testing** (slice/invariance/directional tests), `DVC` data versioning, `MLflow` registry, and modular ML serving/retraining CI/CD. |
| **`NirDiamant/RAG_Techniques`** | **Lab 4 (RAG Suite)** | Cherry-pick ONLY the 6 production RAG patterns above and benchmark each against your baseline eval suite (prove recall gain vs. latency cost). |
| **`patchy631/ai-engineering-hub`** | **Lab 4 (Agents/MCP)** | Reference multimodal PDF/table RAG, practical **MCP server** integrations, and LangGraph stateful agent recipes. |
| **`eugeneyan/applied-ml`** *(+ `ml-design-docs`)* | **Weekly Case Study** | Read 1 real FAANG production paper/post per week (Netflix RecSys, Uber Feature Store, DoorDash Ranking, Airbnb Search) and map onto your 45-Min System Design Clock. |
