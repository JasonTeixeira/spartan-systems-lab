"""Contracts for an owned in-process request/telemetry example."""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "labs/observability-contract/system.py"
spec = importlib.util.spec_from_file_location("observability_contract", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ObservabilityContractTests(unittest.TestCase):
    def test_repair_handles_zero_and_fault_is_visible(self):
        faulty = mod.Service("faulty")
        fixed = mod.Service("repaired")
        self.assertEqual(faulty.request("a", [0, 4])["status"], 500)
        response = fixed.request("a", [0, 4])
        self.assertEqual(response, {"request_id": "a", "status": 200, "total": 4})
        self.assertEqual(faulty.metrics()["server_errors"], 1)
        self.assertEqual(fixed.metrics()["server_errors"], 0)
        self.assertEqual(fixed.metrics()["successes"], 1)

    def test_reject_is_client_error_and_does_not_execute_transform(self):
        service = mod.Service("faulty")
        self.assertEqual(service.request("bad", [True])["status"], 400)
        self.assertEqual(service.metrics()["client_errors"], 1)
        self.assertEqual(service.metrics()["server_errors"], 0)
        events = [json.loads(line) for line in service.logs()]
        self.assertEqual([e["event"] for e in events], ["request_start", "request_end"])
        self.assertEqual([s["stage"] for s in service.trace("bad")], ["validate"])

    def test_logs_traces_metrics_correlate_without_leaking_values(self):
        service = mod.Service("faulty")
        service.request("normal", [3, 5])
        service.request("zero", [0, 4])
        events = [json.loads(line) for line in service.logs()]
        self.assertEqual([e["request_id"] for e in events], ["normal", "normal", "zero", "zero"])
        self.assertEqual([e["status"] for e in events if e["event"] == "request_end"], [200, 500])
        self.assertNotIn("values", "".join(service.logs()))
        self.assertEqual([x["stage"] for x in service.trace("zero")], ["validate", "transform"])
        self.assertEqual([x["outcome"] for x in service.trace("zero")], ["valid", "error"])
        for span in service.trace("zero"):
            self.assertGreaterEqual(span["duration_ns"], 0)
            self.assertEqual(span["request_id"], "zero")
        metrics = service.metrics()
        self.assertEqual(
            (
                metrics["requests"],
                metrics["successes"],
                metrics["client_errors"],
                metrics["server_errors"],
            ),
            (2, 1, 0, 1),
        )
        self.assertGreaterEqual(metrics["duration_ns_sum"], 0)

    def test_changed_case_and_identity_contract(self):
        service = mod.Service("repaired")
        self.assertEqual(service.request("changed", [0, 2, 8])["total"], 10)
        with self.assertRaises(ValueError):
            service.request("changed", [2])
        for bad in ["", "too long " + "x" * 80, "../bad"]:
            with self.assertRaises(ValueError):
                service.request(bad, [1])
        self.assertEqual(service.metrics()["requests"], 1)
        with self.assertRaises(KeyError):
            service.trace("not-seen")

    def test_bounds_and_snapshot_isolation(self):
        service = mod.Service("repaired")
        for i, payload in enumerate(([], [1001], [-1], [1.5], [1] * 101, "bad")):
            self.assertEqual(service.request(f"bad{i}", payload)["status"], 400)
        self.assertEqual(service.metrics()["client_errors"], 6)
        before = service.metrics()
        before["requests"] = -1
        trace = service.trace("bad0")
        trace.clear()
        self.assertEqual(service.metrics()["requests"], 6)
        self.assertEqual(len(service.trace("bad0")), 1)

    def test_mode_and_capacity(self):
        with self.assertRaises(ValueError):
            mod.Service("other")
        service = mod.Service("repaired")
        for i in range(128):
            service.request(f"r{i}", [1])
        with self.assertRaises(ValueError):
            service.request("overflow", [1])
        self.assertEqual(service.metrics()["requests"], 128)

    def test_demo_subprocess_reports_observed_comparison(self):
        proc = subprocess.run(
            [sys.executable, str(PATH.parent / "demo.py")],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        report = json.loads(proc.stdout)
        self.assertEqual(report["observations"]["faulty"]["metrics"]["server_errors"], 2)
        self.assertEqual(report["observations"]["repaired"]["metrics"]["server_errors"], 0)
        self.assertEqual(report["observations"]["repaired"]["metrics"]["client_errors"], 1)
        self.assertIn("labs/observability-contract/system.py", report["source_hashes"])


if __name__ == "__main__":
    unittest.main()
