# Spartan Self-Contained Pure-Python Micro-Labs (`make drill-labs`)

9 zero-dependency, pure-stdlib Python break-fix micro-labs (`93` unit tests + `74` subtests) consolidated into `spartan-systems-lab` so your entire hands-on gym lives in one clean, portable repository.

```bash
make drill-labs
# Or run any individual lab test suite:
uv run pytest drills/micro-labs/tests/test_git_recovery_drill.py -v
```

| Module | Micro-Lab | What You Practice | Run Command |
| :---: | :--- | :--- | :--- |
| **M01 / M03** | `labs/git-recovery-drill/` | Disposable Git stash, reflog, reset, and brownfield recovery surgery | `uv run python drills/micro-labs/labs/git-recovery-drill/system.py` |
| **M02** | `labs/postgres-transfer/` | Native PostgreSQL atomic transfers, idempotency keys & retry safety | `uv run python drills/micro-labs/labs/postgres-transfer/demo.py` |
| **M03 / M11** | `labs/observability-contract/` | Joined structured logs, RED metrics & request-ID trace correlation | `uv run python drills/micro-labs/labs/observability-contract/demo.py` |
| **M06 / M11** | `labs/platform-delivery-contract/` | Gated canary evaluation, error-budget rollback & recovery probes | `uv run python drills/micro-labs/labs/platform-delivery-contract/demo.py` |
| **M06 / M11** | `labs/credential-leak/` | Secret/credential leak detection scanner, redaction & exit codes | `uv run python drills/micro-labs/labs/credential-leak/scanner.py --self-check` |
| **M08** | `labs/chunk-boundary/` | Boundary-aware chunking & associative reduction across evidence windows | `uv run python drills/micro-labs/labs/chunk-boundary/system.py` |
| **M08** | `labs/grounded-retrieval/` | Grounded RAG citation contract, refusal behavior & Recall@K | `uv run python drills/micro-labs/labs/grounded-retrieval/system.py --self-check` |
| **M08** | `labs/beir-ranking/` | Exact IR ranking metrics (linear TREC NDCG, MRR, Recall@K, macro denom) | `uv run pytest drills/micro-labs/tests/test_beir_ranking_metrics.py -v` |
| **M08 / M09** | `labs/agent-loop-budget/` | Hard attempt budgets, loop breakers & denied-tool containment | `uv run python drills/micro-labs/labs/agent-loop-budget/system.py` |
