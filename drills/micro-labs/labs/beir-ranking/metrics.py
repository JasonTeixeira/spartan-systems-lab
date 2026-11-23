"""Independent ordered-ranking nDCG scorer; no retrieval or source-model claim.

Matches the linear relevance gain and log2(rank+1) discount documented by
trec_eval's m_ndcg_cut.c. Accepts already ordered document IDs: score sorting,
tie-breaking, dataset conversion and actual official inference are separate.
"""

import math


def _ids(values, limit):
    if type(values) is not list or not 0 < len(values) <= limit:
        raise ValueError("nonempty bounded identity list required")
    if any(
        type(v) is not str
        or not 0 < len(v) <= 200
        or not v.isprintable()
        or any(c.isspace() for c in v)
        for v in values
    ):
        raise ValueError("invalid identity")
    if len(set(values)) != len(values):
        raise ValueError("duplicate identity")
    return set(values)


def evaluate(query_ids, corpus_ids, qrels, rankings, k=10):
    """Macro-average across EVERY explicit query, including empty rankings.

    Zero ideal DCG has declared score zero. Judgments are integer gains0..100;
    negative/unjudged-label formats must be converted explicitly beforehand.
    At most1000 ranked IDs per query,100k queries and1M corpus IDs. No writes.
    These are fixture safety limits, not limits of nDCG or benchmark policy.
    """
    queries = _ids(query_ids, 100_000)
    corpus = _ids(corpus_ids, 1_000_000)
    if type(k) is not int or not 1 <= k <= 1000:
        raise ValueError("cutoff must be integer1..1000")
    if (
        type(qrels) is not dict
        or type(rankings) is not dict
        or set(qrels) != queries
        or set(rankings) != queries
    ):
        raise ValueError("exact declared query coverage required")
    per_query = {}
    empty = 0
    for query in query_ids:
        grades, ordered = qrels[query], rankings[query]
        if type(grades) is not dict or not set(grades) <= corpus:
            raise ValueError("judgment identity not in corpus")
        if any(type(g) is not int or not 0 <= g <= 100 for g in grades.values()):
            raise ValueError("integer gains0..100 required")
        if type(ordered) is not list or len(ordered) > 1000:
            raise ValueError("bounded ordered ranking required")
        if any(type(d) is not str or d not in corpus for d in ordered):
            raise ValueError("ranked identity not in corpus")
        if len(set(ordered)) != len(ordered):
            raise ValueError("duplicate ranked identity")
        empty += not ordered
        dcg = math.fsum(
            grades.get(doc, 0) / math.log2(rank + 2) for rank, doc in enumerate(ordered[:k])
        )
        ideal = math.fsum(
            grade / math.log2(rank + 2)
            for rank, grade in enumerate(sorted(grades.values(), reverse=True)[:k])
        )
        per_query[query] = dcg / ideal if ideal else 0.0
    return {
        "cutoff": k,
        "gain": "linear-relevance",
        "queries": len(query_ids),
        "empty_rankings": empty,
        "per_query": per_query,
        "mean_ndcg": math.fsum(per_query.values()) / len(query_ids),
    }
