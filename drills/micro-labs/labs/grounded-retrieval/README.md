# Local retrieval and extractive answer lab

Read the [maintained C04 lesson](../../teaching/ai/grounded-retrieval/lesson.md). Python standard library only. This computes scores from raw local documents, composes an exact quote, verifies its retrieved source span, and refuses unsupported evidence. It does not run an LLM or establish semantic faithfulness.

From the project root:

```bash
python3 labs/grounded-retrieval/system.py
```

Expected exit 0 and answer `Atlas retention period is 30 days. [atlas-policy:0:34]`, with a retrieval trace and exact-support checks.

Run this separately:

```bash
python3 labs/grounded-retrieval/system.py --question "What is the trading fee for Atlas?"
```

Expected exit 1 and `no_matching_fact`. Similarity clears the threshold, but the source cannot answer the requested attribute. Malformed inputs/pipeline errors exit 2. Never suppress those outcomes in a gate.

```bash
python3 labs/grounded-retrieval/system.py --self-check
python3 -m unittest discover -s tests -p test_grounded_retrieval.py -v
```

Both verification commands should exit 0. Self-check uses default k/threshold and the six cases in the [assessment contract](../../teaching/ai/grounded-retrieval/exercise.json); annotations do not enter `answer()`. The tests also mutate sources, remove evidence, inject bad claims and citations, and create conflicts/retrieval misses.

Question grammar: `What is [the] <attribute> for <entity>?`. Source grammar: `<entity> <attribute> is <value>.`, one fact per line. Citations use unchanged-source Unicode character offsets, start inclusive/end exclusive. The corpus contains only fictional records. No model API, credentials, external calls, copied program execution, source writes, or progress updates occur.
