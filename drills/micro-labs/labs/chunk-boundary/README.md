# Boundary-aware counting fixture

From the project root:

```bash
python3 labs/chunk-boundary/system.py
python3 -m unittest discover -s tests -p 'test_chunk_boundary.py'
```

Python standard library only; pure functions and stdout. No network, imported execution, personal-progress writes or provider calls.

For changed cases:

```python
import importlib.util

spec = importlib.util.spec_from_file_location("chunks", "labs/chunk-boundary/system.py")
chunks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chunks)
print(chunks.analyze("ab cdef gh", 1))
print(chunks.reduce_chunks(["a", " ", "b"]))
```

`analyze` validates text of at most 4,096 Unicode scalar values and exact integer size 1..256. The helper summaries/merge accept trusted internally generated summaries and are not a public untrusted-summary validation API. Counting uses Python Unicode whitespace; it is not linguistic words, provider tokens, a summary or a prompt-injection defense. Empty text counts zero. [Teaching](../../teaching/chunk-boundary/index.md) includes the exact source defect, invariant, practice and feedback.

Evidence: the initial red log records missing implementation, not execution of the old algorithm. The retained author observation directly reproduces 16 naive fragments versus 15 whole-input words. The surrogate-before log passes under broad ValueError catching (UnicodeEncodeError is a subclass); final tests check exact ValueError after explicit rejection. No misleading red/green claim follows from that log.
