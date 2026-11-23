# Local request observability fixture

Run from the ecosystem root:

```sh
python3 labs/observability-contract/demo.py
python3 -m unittest discover -s tests -p 'test_observability_contract.py'
```

A sequential in-process service admits at most 128 caller-supplied unique IDs; invalid/duplicate IDs raise before admission and are excluded from logs and metrics. Each admitted request validates a list of 1–100 integers from 0 to 1000 (booleans rejected). Faulty mode performs an unnecessary division by each value; a valid zero raises `ZeroDivisionError` and becomes a 500. Repaired mode removes that probe and returns the integer sum. Invalid payloads return 400; successful valid payloads return 200. The two modes are deliberately authored examples, not evidence of a defect in an external service.

Read start/end JSON log objects by request ID, stage traces with actual `perf_counter_ns` elapsed durations and outcomes, and aggregate request/status counters plus elapsed sum. They are separate views of the same in-memory sequential calls; the ID is supplied, not authenticated, and log records contain no input values. Snapshot methods return copies. A 500 here is a caught expected toy exception; unexpected exceptions propagate and are not claimed to be comprehensively instrumented.

The [retained author run](../../proof/observability-contract-author-observation.json) records real local times and environment; timings vary. Duration includes local instrumentation, and no network, HTTP transport, distributed tracing, histogram/percentiles, monitoring backend, concurrent load, durable logs, production SLO, learner or specialist review is established. Source hashes before and after assume a trusted filesystem, not continuous attestation. Independent tests cover the changed case and telemetry distinctions; see [the lesson](../../teaching/observability-contract/index.md) and [separate feedback](../../teaching/observability-contract/feedback.md).
