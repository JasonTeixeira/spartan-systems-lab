"""Owned bounded text-count fixture; no model/provider or imported code."""

import hashlib
import json
import re

EXAMPLE = "the quick brown fox jumps over the lazy dog and then runs far away home"


def summarize(text):
    words = 0
    inside = False
    for character in text:
        nonspace = not character.isspace()
        if nonspace and not inside:
            words += 1
        inside = nonspace
    return {
        "length": len(text),
        "words": words,
        "starts_word": bool(text) and not text[0].isspace(),
        "ends_word": bool(text) and not text[-1].isspace(),
    }


def merge(left, right):
    if not left["length"]:
        return dict(right)
    if not right["length"]:
        return dict(left)
    return {
        "length": left["length"] + right["length"],
        "words": left["words"] + right["words"] - int(left["ends_word"] and right["starts_word"]),
        "starts_word": left["starts_word"],
        "ends_word": right["ends_word"],
    }


def reduce_chunks(chunks):
    summary = summarize("")
    for chunk in chunks:
        summary = merge(summary, summarize(chunk))
    return summary


def analyze(text, size):
    if (
        type(text) is not str
        or len(text) > 4096
        or type(size) is not int
        or not 1 <= size <= 256
        or any(0xD800 <= ord(c) <= 0xDFFF for c in text)
    ):
        raise ValueError("text <=4096 Unicode scalar values and exact integer size1..256 required")
    chunks = [text[i : i + size] for i in range(0, len(text), size)]
    return {
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "chunk_size_codepoints": size,
        "chunks": chunks,
        "naive_words": sum(len(chunk.split()) for chunk in chunks),
        "repaired_words": reduce_chunks(chunks)["words"],
        "whole_words": len(re.findall(r"\S+", text)),
        "definition": "Maximal runs of Python Unicode non-whitespace code points; not linguistic words or model tokens.",
    }


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "original": analyze(EXAMPLE, 20),
                "changed": analyze("ab cdef gh", 1),
                "limits": "Ordered exact counting only; data traversal does not guarantee semantic summary coverage. No provider/model/context-window evaluation.",
            },
            indent=2,
        )
    )
