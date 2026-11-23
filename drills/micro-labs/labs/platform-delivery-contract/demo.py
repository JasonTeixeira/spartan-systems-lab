"""Execute a local release sequence with actual observed canary results."""

import hashlib
import json
from pathlib import Path

from system import Platform


def main():
    root = Path(__file__).resolve().parents[2]
    prefix = "labs/platform-delivery-contract/"
    paths = [
        prefix + p for p in ("system.py", "demo.py", "stable.json", "buggy.json", "fixed.json")
    ]
    before = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    stable, buggy, fixed = [
        (root / (prefix + p)).read_bytes() for p in ("stable.json", "buggy.json", "fixed.json")
    ]
    platform = Platform(stable)
    policy = {"target": "local", "max_errors": 0}
    cases = {}
    cases["faulty_rollout"] = platform.release(buggy, policy, [0, 2, 4, 0])
    cases["repair_rollout"] = platform.release(fixed, policy, [0, 2, 4, 0])
    cases["denied_target"] = platform.release(buggy, {"target": "external", "max_errors": 0}, [0])
    cases["failed_tests"] = platform.release(
        b'{"name":"bad-test","mode":"always_error"}', policy, [0]
    )
    if before != {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}:
        raise RuntimeError("input files changed during observation")
    print(
        json.dumps(
            {
                "source_hashes": before,
                "cases": cases,
                "selected": platform.selected(),
                "limits": "Sequential in-process data-only local model. No CI provider, real traffic, identity or authorization, network, durable deployment, concurrency or production health claim. Observed times include local interpreter work and are not a benchmark. Hashes assume a trusted filesystem.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
