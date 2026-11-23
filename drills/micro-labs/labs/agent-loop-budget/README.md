# Charge every attempted action

From the project root:

```bash
python3 labs/agent-loop-budget/system.py
python3 -m unittest discover -s tests -p 'test_agent_loop_budget.py'
```

Standard-library Python, scripted requests and one pure local arithmetic tool. No model, network, external tool, filesystem write or personal history is involved. `run` accepts an iterable and a strict integer attempt budget1–32. The fixed grants are trusted code; text in a request cannot expand them. `finish` requests a stop and does not establish goal correctness.

A returned request consumes one attempt before malformed/denied/invalid branches. The runner does not pull an extra request to distinguish exact-length exhaustion at the budget boundary. Provider exceptions propagate; no partial success report is returned. The source iterator is trusted to return or raise: a blocked `next` cannot be bounded by a step counter. There is no whole-run wall-clock, provider-token, external-side-effect, cancellation or cost guarantee.

[Study the correction](../../teaching/agent-loop-budget/index.md), predict the traces and attempt the independent challenge before feedback. This repairs particular control-order/argument assumptions without approving the original selected agent course.
