# Independent ranking metric component

This component scores already ordered rankings. It does not retrieve documents, run Anserini, reproduce BEIR or close `ai-research-route`.

From the ecosystem root:

```sh
python3 -m unittest discover -s tests -p test_beir_ranking_metrics.py
```

`metrics.evaluate(query_ids, corpus_ids, qrels, rankings, k=10)` requires the exact declared query set in both maps. Every query contributes to the macro average; an explicit empty ranking scores zero. Missing or extra query rows are rejected rather than silently changing the denominator. Documents must belong to the declared corpus and ranked IDs cannot repeat.

The [primary trec_eval implementation](https://raw.githubusercontent.com/usnistgov/trec_eval/main/m_ndcg_cut.c) documents **linear relevance gain**, discounted by `log2(rank+1)` for one-based rank. Do not substitute exponential gain and label it the same calculation. A query with zero ideal DCG scores zero here. Graded judgments must be integers from0through100; negative-label conversion must be explicit. Ranking lists are limited to1000IDs, corpus to1million IDs and queries to100,000. These are local safety bounds, not benchmark policies.

The hand-calculated graded example distinguishes linear from exponential gain; empty results, unknown identities, invalid grades and changed cutoff cases are tested. No labels enter an inference pipeline here because there is **no inference pipeline yet**. The future actual retrieval runner must keep qrels out of inference and retain full query/ranking identities, scores, tie handling, hashes and failures. Ordered-list scoring alone does not prove official sorting or tie semantics.

Primary-source preparation and remaining reproduction constraints are in `proof/beir-baseline-provenance-review.json`, `proof/beir-inference-path-review.json` and `proof/beir-inference-path-followup-review.json`. The pinned later Anserini code is not established as the original2021implementation. Dataset terms, exact conversion, source/runtime setup, complete official evaluation and qualified outside criticism remain separate gates. No original sources or learner history are changed.
