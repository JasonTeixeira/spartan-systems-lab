"""Bounded, sequential in-process service and local observability fixture.

The faulty mode deliberately raises for a valid zero. No network or durable
telemetry collector is involved; the caller supplies a unique public ID.
"""

import copy
import json
import re
import time

_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")


class Service:
    def __init__(self, mode):
        if mode not in ("faulty", "repaired"):
            raise ValueError("mode must be faulty or repaired")
        self.mode = mode
        self._logs = []
        self._traces = {}
        self._metrics = dict(
            requests=0, successes=0, client_errors=0, server_errors=0, duration_ns_sum=0
        )

    def request(self, request_id, values):
        # Invalid or duplicate IDs are rejected before admission: no telemetry
        # or aggregate request is recorded for that caller-side misuse.
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise ValueError("invalid request ID")
        if request_id in self._traces or len(self._traces) >= 128:
            raise ValueError("duplicate ID or service request capacity reached")
        spans = []
        self._traces[request_id] = spans
        self._logs.append(json.dumps({"request_id": request_id, "event": "request_start"}))
        start = time.perf_counter_ns()
        stage_start = time.perf_counter_ns()
        valid = (
            isinstance(values, list)
            and 1 <= len(values) <= 100
            and all(type(v) is int and 0 <= v <= 1000 for v in values)
        )
        spans.append(
            {
                "request_id": request_id,
                "stage": "validate",
                "duration_ns": time.perf_counter_ns() - stage_start,
                "outcome": "valid" if valid else "invalid",
            }
        )
        result = {"request_id": request_id}
        if not valid:
            status = 400
        else:
            stage_start = time.perf_counter_ns()
            try:
                if self.mode == "faulty":
                    # Authored defect: an unnecessary reciprocal probe makes
                    # otherwise valid zero fail before the actual sum.
                    for value in values:
                        1 // value
                result["total"] = sum(values)
                status = 200
            except ZeroDivisionError:
                status = 500
            finally:
                spans.append(
                    {
                        "request_id": request_id,
                        "stage": "transform",
                        "duration_ns": time.perf_counter_ns() - stage_start,
                        "outcome": "ok" if status == 200 else "error",
                    }
                )
        elapsed = time.perf_counter_ns() - start
        result["status"] = status
        self._metrics["requests"] += 1
        self._metrics[{200: "successes", 400: "client_errors", 500: "server_errors"}[status]] += 1
        self._metrics["duration_ns_sum"] += elapsed
        self._logs.append(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "request_end",
                    "status": status,
                    "duration_ns": elapsed,
                }
            )
        )
        return result

    def logs(self):
        return list(self._logs)

    def metrics(self):
        return self._metrics.copy()

    def trace(self, request_id):
        return copy.deepcopy(self._traces[request_id])
