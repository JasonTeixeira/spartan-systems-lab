"""Bounded sequential local deployment model over data-only JSON artifacts.

No arbitrary code, network, cloud, durable store or authenticated actors.
"""

import hashlib
import json
import re
import time


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _artifact(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= 4096:
        raise ValueError("artifact must be bounded bytes")
    try:
        data = json.loads(raw, object_pairs_hook=_object)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError("invalid artifact JSON") from exc
    if (
        type(data) is not dict
        or set(data) != {"name", "mode"}
        or type(data["name"]) is not str
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,23}", data["name"]) is None
        or type(data["mode"]) is not str
        or data["mode"] not in ("safe", "zero_fault", "always_error")
    ):
        raise ValueError("invalid artifact schema")
    return data, hashlib.sha256(raw).hexdigest()


def _run(config, value):
    if config["mode"] == "always_error":
        raise ArithmeticError("toy fault")
    if config["mode"] == "zero_fault":
        1 // value
    return value


def _case(config, value):
    try:
        result = _run(config, value)
    except ArithmeticError:
        return None
    return result


class Platform:
    """A single selection; canary briefly selects candidate then may restore."""

    def __init__(self, baseline):
        config, digest = _artifact(baseline)
        # Exhaust all six inputs in this fictional finite domain for startup.
        if any(_case(config, n) != n for n in range(6)):
            raise ValueError("initial baseline fails full finite-domain check")
        self._active = (config, digest)
        self._attempts = 0

    def selected(self):
        return self._active[0]["name"]

    def selected_sha256(self):
        return self._active[1]

    def execute(self, value):
        if type(value) is not int or not 0 <= value <= 5:
            raise ValueError("input must be integer 0..5")
        return _run(self._active[0], value)

    def release(self, raw, policy, requests):
        config, digest = _artifact(raw)
        if (
            type(policy) is not dict
            or set(policy) != {"target", "max_errors"}
            or type(policy["target"]) is not str
            or policy["target"] not in ("local", "external")
            or type(policy["max_errors"]) is not int
            or policy["max_errors"] not in (0, 1)
        ):
            raise ValueError("invalid policy")
        if (
            type(requests) is not list
            or not 1 <= len(requests) <= 20
            or any(type(x) is not int or not 0 <= x <= 5 for x in requests)
        ):
            raise ValueError("invalid canary requests")
        if self._attempts >= 64:
            raise ValueError("attempt capacity reached")
        self._attempts += 1
        output = {
            "artifact_sha256": digest,
            "selection_history": [self.selected()],
            "selection_sha256_history": [self.selected_sha256()],
        }
        # The small release test intentionally misses the zero-specific fault.
        results = [_case(config, n) for n in (2, 3)]
        output["tests"] = {
            "inputs": [2, 3],
            "outputs": results,
            "passed": results == [2, 3],
        }
        if not output["tests"]["passed"]:
            output["gate"] = "test_failed"
            return output
        if policy["target"] != "local":
            output["gate"] = "policy_denied"
            return output
        previous = self._active
        self._active = (config, digest)
        output["selection_history"].append(self.selected())
        output["selection_sha256_history"].append(self.selected_sha256())
        try:
            start = time.perf_counter_ns()
            results = [_case(config, x) for x in requests]
            elapsed = time.perf_counter_ns() - start
            errors = sum(result != value for result, value in zip(results, requests, strict=True))
            output["canary"] = {
                "inputs": list(requests),
                "outputs": results,
                "requests": len(requests),
                "errors": errors,
                "duration_ns": elapsed,
            }
            if errors > policy["max_errors"]:
                self._active = previous
                output["selection_history"].append(self.selected())
                output["selection_sha256_history"].append(self.selected_sha256())
                output["gate"] = "rollback"
                output["recovery"] = {
                    "name": self.selected(),
                    "input": 0,
                    "output": _case(self._active[0], 0),
                }
            else:
                output["gate"] = "promote"
            return output
        except BaseException:
            self._active = previous
            raise
