"""Strict BEIR inputs and ordered TREC run parsing; no execution or writes."""

import csv
import hashlib
import io
import json
import math


def _identity(value):
    if (
        type(value) is not str
        or not 0 < len(value) <= 200
        or not value.isprintable()
        or any(c.isspace() for c in value)
    ):
        raise ValueError("invalid identity")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"nonfinite JSON constant: {value}")


def _read(path):
    # Trusted author paths/filesystem; no hostile concurrent substitution claim.
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("missing or oversized input")
    raw = path.read_bytes()
    if not raw or len(raw) > 64 * 1024 * 1024:
        raise ValueError("empty or oversized input")
    return raw


def _json_rows(raw, corpus):
    rows = {}
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line, object_pairs_hook=_object, parse_constant=_reject_constant)
        if type(row) is not dict:
            raise ValueError("JSON row must be object")
        identity = _identity(row.get("_id"))
        if identity in rows:
            raise ValueError("duplicate row identity")
        if type(row.get("text")) is not str or not row["text"].strip():
            raise ValueError("nonempty text required")
        if corpus and type(row.get("title")) is not str:
            raise ValueError("explicit corpus title required, empty allowed")
        if not corpus and any(c in row["text"] for c in "\t\n\r"):
            raise ValueError("query would change under TSV conversion")
        rows[identity] = row
    if not rows:
        raise ValueError("no JSON rows")
    return rows


def prepare(root):
    """Test membership comes from qrel IDs, never positive-grade filtering.

    Complete original corpus retained; topics contain only IDs/query text.
    Public split membership is not a hidden-label guarantee. No model invoked.
    """
    names = ["corpus.jsonl", "queries.jsonl", "qrels/test.tsv"]
    raw = {name: _read(root / name) for name in names}
    corpus = _json_rows(raw["corpus.jsonl"], True)
    queries = _json_rows(raw["queries.jsonl"], False)
    reader = csv.reader(io.StringIO(raw["qrels/test.tsv"].decode("utf-8")), delimiter="\t")
    if next(reader, None) != ["query-id", "corpus-id", "score"]:
        raise ValueError("unexpected qrel header")
    qrels = {}
    for row in reader:
        if len(row) != 3:
            raise ValueError("invalid qrel row")
        query, doc, grade = row
        if query not in queries or doc not in corpus:
            raise ValueError("qrel identity outside inputs")
        if not grade.isascii() or not grade.isdecimal() or not 0 <= int(grade) <= 100:
            raise ValueError("invalid integer gain")
        if doc in qrels.setdefault(query, {}):
            raise ValueError("duplicate judgment")
        qrels[query][doc] = int(grade)
    if not qrels:
        raise ValueError("no test queries")
    query_ids = sorted(qrels)
    topics = "".join(f"{q}\t{queries[q]['text']}\n" for q in query_ids)
    return {
        "corpus_ids": list(corpus),
        "query_ids": query_ids,
        "qrels": qrels,
        "topics": topics,
        "topics_sha256": hashlib.sha256(topics.encode()).hexdigest(),
        "input_hashes": {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
    }


def parse_run(text, query_ids, corpus_ids):
    """Validate emitted rank order; absent rows do NOT prove zero-hit execution.

    Caller must separately verify official command completion/query counts.
    Rounded TREC scores cannot establish exact internal tie semantics.
    """
    if type(text) is not str or len(text) > 128 * 1024 * 1024:
        raise ValueError("bounded text required")
    if (
        type(query_ids) is not list
        or type(corpus_ids) is not list
        or not query_ids
        or not corpus_ids
    ):
        raise ValueError("nonempty identity lists required")
    if len(set(query_ids)) != len(query_ids) or len(set(corpus_ids)) != len(corpus_ids):
        raise ValueError("duplicate declared identity")
    for value in query_ids + corpus_ids:
        _identity(value)
    corpus = set(corpus_ids)
    rankings = {query: [] for query in query_ids}
    previous = {}
    seen = {query: set() for query in query_ids}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 6:
            raise ValueError("TREC row must have six fields")
        query, iteration, doc, rank, score, tag = fields
        if query not in rankings or doc not in corpus or iteration != "Q0":
            raise ValueError("unknown run identity/iteration")
        if (
            not rank.isascii()
            or not rank.isdecimal()
            or int(rank) != len(rankings[query]) + 1
            or int(rank) > 1000
        ):
            raise ValueError("noncontiguous or oversized rank")
        value = float(score)
        if not math.isfinite(value) or value > previous.get(query, math.inf):
            raise ValueError("nonfinite or increasing run score")
        if doc in seen[query]:
            raise ValueError("duplicate run document")
        _identity(tag)
        rankings[query].append(doc)
        seen[query].add(doc)
        previous[query] = value
    return {
        "rankings": rankings,
        "queries_with_no_rows": [q for q in query_ids if not rankings[q]],
        "proves_all_queries_executed": False,
    }
