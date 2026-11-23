"""Run a fixed local comparison, with actual per-request records."""

import hashlib
import json
import platform
import sys
from pathlib import Path

from system import Service


def main():
    root = Path(__file__).resolve().parents[2]
    paths = [
        "labs/observability-contract/system.py",
        "labs/observability-contract/demo.py",
    ]
    before = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    observations = {}
    for mode in ("faulty", "repaired"):
        service = Service(mode)
        results = [
            service.request("normal", [3, 5]),
            service.request("zero", [0, 4]),
            service.request("invalid", [True]),
            service.request("changed", [0, 2, 8]),
        ]
        observations[mode] = {
            "responses": results,
            "logs": [json.loads(x) for x in service.logs()],
            "metrics": service.metrics(),
            "traces": {i: service.trace(i) for i in ("normal", "zero", "invalid", "changed")},
        }
    after = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    if before != after:
        raise RuntimeError("source changed during observation")
    print(
        json.dumps(
            {
                "python": sys.version,
                "platform": platform.platform(),
                "source_hashes": before,
                "observations": observations,
                "limits": "Sequential in-process fixture; monotonic elapsed time includes instrumentation. Hash checks assume a trusted filesystem and do not attest continuous execution. No network, distributed tracing, external collector, production throughput, real learner or specialist evidence.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
