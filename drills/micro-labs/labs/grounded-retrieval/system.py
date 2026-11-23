"""C04 local retrieval + extractive answers; no LLM, network or source execution."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus.json"
CONTRACT = Path(__file__).resolve().parents[2] / "teaching/ai/grounded-retrieval/exercise.json"
MAX_INPUT_BYTES = 65_536
MAX_TEXT_BYTES = 16_384
MAX_DOCUMENTS = 20
MAX_CHUNKS = 200
ID = re.compile(r"[a-z][a-z0-9-]{0,47}")
STOP = {"what", "is", "the", "for"}
QUESTION = re.compile(
    r"what is (?:the )?([a-z][a-z0-9 ]{0,63}?) for ([a-z][a-z0-9-]{0,31})\??", re.I
)
FACT = re.compile(r"([a-z][a-z0-9-]{0,31}) ([a-z][a-z0-9 ]{0,63}?) is (.+)\.", re.I)


def validate_corpus(corpus: dict) -> None:
    if not isinstance(corpus, dict) or set(corpus) != {"schema_version", "documents"}:
        raise ValueError("Invalid corpus schema.")
    if type(corpus["schema_version"]) is not int or corpus["schema_version"] != 1:
        raise ValueError("Invalid corpus version.")
    documents = corpus["documents"]
    if not isinstance(documents, list) or len(documents) > MAX_DOCUMENTS:
        raise ValueError("Invalid document collection.")
    seen = set()
    line_count = 0
    for doc in documents:
        if not isinstance(doc, dict) or set(doc) != {"id", "text"}:
            raise ValueError("Invalid document schema.")
        if not isinstance(doc["id"], str) or not ID.fullmatch(doc["id"]) or doc["id"] in seen:
            raise ValueError("Invalid or duplicate document ID.")
        if (
            not isinstance(doc["text"], str)
            or not doc["text"].strip()
            or len(doc["text"].encode("utf-8")) > MAX_TEXT_BYTES
        ):
            raise ValueError("Invalid document text.")
        line_count += len(doc["text"].splitlines())
        seen.add(doc["id"])
    if line_count > MAX_CHUNKS:
        raise ValueError("Too many document lines.")


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field.")
        result[key] = value
    return result


def read_corpus(path: Path) -> dict:
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Not a regular local fixture.")
        with path.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Input exceeds fixture limit.")
        corpus = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        validate_corpus(corpus)
        return corpus
    except (OSError, ValueError) as error:
        raise ValueError("Corpus could not be read or validated.") from error


def chunks(corpus: dict) -> list[dict]:
    validate_corpus(corpus)
    result = []
    for doc in corpus["documents"]:
        offset = 0
        for number, line in enumerate(doc["text"].splitlines(keepends=True), 1):
            text = line.rstrip("\r\n")
            if text.strip():
                result.append(
                    {
                        "chunk_id": f"{doc['id']}:L{number}",
                        "document_id": doc["id"],
                        "start": offset,
                        "end": offset + len(text),
                        "text": text,
                    }
                )
            offset += len(line)
    return result


def terms(text: str) -> Counter:
    return Counter(t for t in re.findall(r"[a-z0-9]+", text.casefold()) if t not in STOP)


def retrieve(question: str, corpus: dict, k: int = 3) -> list[dict]:
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        raise ValueError("Question must contain 1 to 500 characters.")
    if type(k) is not int or not 1 <= k <= 20:
        raise ValueError("k must be 1 to 20.")
    query = terms(question)
    query_norm = math.sqrt(sum(n * n for n in query.values()))
    scored = []
    for chunk in chunks(corpus):
        vector = terms(chunk["text"])
        norm = math.sqrt(sum(n * n for n in vector.values()))
        dot = sum(n * vector[t] for t, n in query.items())
        score = dot / (query_norm * norm) if query_norm and norm else 0.0
        scored.append(dict(chunk, score=score))
    return sorted(scored, key=lambda row: (-row["score"], row["chunk_id"]))[:k]


def parse_question(question: str) -> tuple[str, str] | None:
    match = QUESTION.fullmatch(" ".join(question.strip().split()))
    return (match[2].casefold(), match[1].casefold()) if match else None


def fact_value(text: str, target: tuple[str, str] | None) -> str | None:
    match = FACT.fullmatch(text)
    if match and target == (match[1].casefold(), match[2].casefold()):
        return match[3]
    return None


def compose(question: str, context: list[dict]) -> list[dict]:
    """Assemble a source quote, not a learned or free-form generated answer."""
    for chunk in context:
        if fact_value(chunk["text"], parse_question(question)) is not None:
            return [
                {
                    "text": chunk["text"],
                    "citation": {key: chunk[key] for key in ["document_id", "start", "end"]},
                }
            ]
    return []


def verify_claim(claim: dict, question: str, corpus: dict, context: list[dict]) -> bool:
    if not isinstance(claim, dict) or set(claim) != {"text", "citation"}:
        return False
    cite = claim["citation"]
    if not isinstance(cite, dict) or set(cite) != {"document_id", "start", "end"}:
        return False
    if not isinstance(claim["text"], str) or not isinstance(cite["document_id"], str):
        return False
    if type(cite["start"]) is not int or type(cite["end"]) is not int:
        return False
    source = next((d["text"] for d in corpus["documents"] if d["id"] == cite["document_id"]), None)
    if source is None or not 0 <= cite["start"] < cite["end"] <= len(source):
        return False
    if not any(all(c[key] == cite[key] for key in cite) for c in context):
        return False
    return (
        source[cite["start"] : cite["end"]] == claim["text"]
        and fact_value(claim["text"], parse_question(question)) is not None
    )


def answer(question: str, corpus: dict, k: int = 3, threshold: float = 0.25) -> dict:
    if (
        type(threshold) not in {int, float}
        or not math.isfinite(threshold)
        or not 0 < threshold <= 1
    ):
        raise ValueError("Threshold must be finite and in (0, 1].")
    retrieved = retrieve(question, corpus, k)
    context = [c for c in retrieved if c["score"] >= threshold]
    report = {
        "question": question,
        "k": k,
        "threshold": threshold,
        "retrieved": retrieved,
        "context": context,
        "action": "refuse",
        "reason": "",
        "claims": [],
        "answer": None,
        "candidate_count": 0,
        "verified_count": 0,
        "exact_support_rate": None,
    }
    target = parse_question(question)
    if target is None:
        report["reason"] = "unsupported_question_form"
    elif not context:
        report["reason"] = "no_retrieval_support"
    else:
        values = {value for c in context if (value := fact_value(c["text"], target)) is not None}
        if not values:
            report["reason"] = "no_matching_fact"
        elif len(values) > 1:
            report["reason"] = "conflicting_sources"
        else:
            candidates = compose(question, context)
            report["candidate_count"] = len(candidates)
            report["verified_count"] = sum(
                verify_claim(c, question, corpus, context) for c in candidates
            )
            report["exact_support_rate"] = (
                report["verified_count"] / len(candidates) if candidates else None
            )
            if not candidates or report["verified_count"] != len(candidates):
                report["reason"] = "unsupported_generated_claim"
            else:
                report.update(action="answer", reason="verified_source_quote", claims=candidates)
                report["answer"] = "\n".join(
                    f"{c['text']} [{c['citation']['document_id']}:{c['citation']['start']}:{c['citation']['end']}]"
                    for c in candidates
                )
    return report


def recall_at_k(report: dict, relevant_chunk_ids: list[str]) -> float | None:
    """Offline annotation metric; never used to retrieve, compose or verify."""
    if (
        not isinstance(relevant_chunk_ids, list)
        or any(not isinstance(x, str) for x in relevant_chunk_ids)
        or len(set(relevant_chunk_ids)) != len(relevant_chunk_ids)
    ):
        raise ValueError("Relevant IDs must be a unique string list.")
    if not relevant_chunk_ids:
        return None
    found = {c["chunk_id"] for c in report["retrieved"]}
    return len(found.intersection(relevant_chunk_ids)) / len(relevant_chunk_ids)


def self_check() -> dict:
    corpus = read_corpus(CORPUS)
    cases = json.loads(CONTRACT.read_text())["cases"]
    results = []
    for case in cases:
        report = answer(case["question"], corpus)
        recall = recall_at_k(report, case["relevant_chunk_ids"])
        passed = (
            report["action"] == case["expected_action"]
            and report["reason"] == case["expected_reason"]
            and [c["text"] for c in report["claims"]] == case["expected_claims"]
            and recall == case["expected_recall_at_k"]
        )
        results.append(
            {
                "case": case["id"],
                "passed": passed,
                "action": report["action"],
                "reason": report["reason"],
                "recall_at_k": recall,
                "exact_support_rate": report["exact_support_rate"],
            }
        )
    return {
        "status": "self-check",
        "passed": bool(results) and all(r["passed"] for r in results),
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--question", default="What is the retention period for Atlas?")
    mode.add_argument("--self-check", action="store_true")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--threshold", type=float, default=0.25)
    args = parser.parse_args(argv)
    try:
        if args.self_check:
            report = self_check()
            code = 0 if report["passed"] else 1
        else:
            report = answer(args.question, read_corpus(CORPUS), args.k, args.threshold)
            code = 0 if report["action"] == "answer" else 1
    except Exception:
        report = {
            "status": "error",
            "code": "invalid-input-or-pipeline-error",
            "scope": "No verified answer was established.",
        }
        code = 2
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
