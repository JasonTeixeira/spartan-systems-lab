"""Checks a local gated delivery and real bounded canary observations."""

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "labs/platform-delivery-contract/system.py"
spec = importlib.util.spec_from_file_location("platform_delivery", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def artifact(name, mode):
    return json.dumps({"name": name, "mode": mode}).encode()


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.platform = m.Platform(artifact("stable", "safe"))

    def test_actual_canary_failure_selects_previous_and_verifies_recovery(self):
        out = self.platform.release(
            artifact("buggy", "zero_fault"),
            {"target": "local", "max_errors": 0},
            [0, 2, 4, 0],
        )
        self.assertEqual(out["gate"], "rollback")
        self.assertEqual(out["canary"]["errors"], 2)
        self.assertEqual(out["canary"]["requests"], 4)
        self.assertEqual(out["selection_history"], ["stable", "buggy", "stable"])
        self.assertEqual(out["recovery"], {"name": "stable", "input": 0, "output": 0})
        self.assertEqual(self.platform.selected(), "stable")
        self.assertGreaterEqual(out["canary"]["duration_ns"], 0)

    def test_repair_promotes_and_changed_case_counts_real_errors(self):
        out = self.platform.release(
            artifact("fixed", "safe"), {"target": "local", "max_errors": 0}, [0, 5, 0]
        )
        self.assertEqual(out["gate"], "promote")
        self.assertEqual(out["canary"]["errors"], 0)
        self.assertEqual(self.platform.selected(), "fixed")
        self.assertEqual(self.platform.execute(5), 5)
        self.assertEqual(len(out["artifact_sha256"]), 64)

    def test_failing_test_and_policy_denial_keep_existing_selection(self):
        failed = self.platform.release(
            artifact("broken", "always_error"),
            {"target": "local", "max_errors": 0},
            [0],
        )
        self.assertEqual(failed["gate"], "test_failed")
        self.assertEqual(self.platform.selected(), "stable")
        denied = self.platform.release(
            artifact("unsafe", "safe"), {"target": "external", "max_errors": 0}, [0]
        )
        self.assertEqual(denied["gate"], "policy_denied")
        self.assertEqual(self.platform.selected(), "stable")
        self.assertNotIn("canary", denied)

    def test_previous_selection_can_be_bad_and_recovery_exposes_it(self):
        accepted = self.platform.release(
            artifact("badprior", "zero_fault"),
            {"target": "local", "max_errors": 0},
            [1, 2],
        )
        self.assertEqual(accepted["gate"], "promote")
        result = self.platform.release(
            artifact("badnext", "zero_fault"),
            {"target": "local", "max_errors": 0},
            [0],
        )
        self.assertEqual(result["gate"], "rollback")
        self.assertEqual(result["recovery"]["name"], "badprior")
        self.assertIsNone(result["recovery"]["output"])

    def test_unexpected_canary_error_restores_selection(self):
        previous = self.platform.selected_sha256()
        original = m._case
        calls = []

        def failure_during_canary(config, value):
            calls.append(value)
            if len(calls) == 3:
                raise RuntimeError("injected failure")
            return original(config, value)

        with patch.object(m, "_case", side_effect=failure_during_canary):
            with self.assertRaises(RuntimeError):
                self.platform.release(
                    artifact("candidate", "safe"),
                    {"target": "local", "max_errors": 0},
                    [0],
                )
        self.assertEqual(self.platform.selected_sha256(), previous)

    def test_baseline_rejects_hidden_zero_fault(self):
        with self.assertRaises(ValueError):
            m.Platform(artifact("bad", "zero_fault"))

    def test_strict_bounds_invalid_input_and_no_mutation(self):
        for bad in [b"{}", b"not-json", b'{"name":"x","mode":"bad"}', b"x" * 4097]:
            with self.assertRaises(ValueError):
                self.platform.release(bad, {"target": "local", "max_errors": 0}, [1])
        for bad in [[], [True], [6], [1] * 21, "x"]:
            with self.assertRaises(ValueError):
                self.platform.release(
                    artifact("x", "safe"), {"target": "local", "max_errors": 0}, bad
                )
        for bad in [
            {"target": "local", "max_errors": True},
            {"target": "local", "max_errors": 2},
            {"target": "local"},
        ]:
            with self.assertRaises(ValueError):
                self.platform.release(artifact("x", "safe"), bad, [1])
        self.assertEqual(self.platform.selected(), "stable")

    def test_sequential_promotions_rollback_to_most_recent_healthy(self):
        self.platform.release(artifact("good2", "safe"), {"target": "local", "max_errors": 0}, [0])
        result = self.platform.release(
            artifact("bad2", "zero_fault"), {"target": "local", "max_errors": 0}, [0]
        )
        self.assertEqual(result["recovery"]["name"], "good2")
        self.assertEqual(self.platform.selected(), "good2")


if __name__ == "__main__":
    unittest.main()
