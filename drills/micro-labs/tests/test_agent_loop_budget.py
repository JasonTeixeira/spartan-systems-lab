import copy
import importlib.util
import itertools
import math
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "agent_budget",
    Path(__file__).resolve().parents[1] / "labs/agent-loop-budget/system.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AgentLoopBudgetTests(unittest.TestCase):
    def test_infinite_all_denied_stream_stops_at_attempt_budget(self):
        seen = []

        def requests():
            for i in itertools.count():
                seen.append(i)
                yield {"tool": "delete", "input": {"row": i}}

        report = m.run(requests(), 4)
        self.assertEqual(seen, [0, 1, 2, 3])
        self.assertEqual(report["attempts"], 4)
        self.assertEqual(report["stop"], "budget")
        self.assertEqual(report["results"], [])
        self.assertEqual([x["outcome"] for x in report["trace"]], ["denied"] * 4)

    def test_repeated_invalid_requests_cannot_bypass_budget(self):
        report = m.run(itertools.repeat(None), 3)
        self.assertEqual(report["attempts"], 3)
        self.assertEqual(report["stop"], "budget")
        self.assertEqual([x["outcome"] for x in report["trace"]], ["malformed"] * 3)
        self.assertEqual(report["results"], [])

    def test_mixed_trace_and_requested_finish_is_not_goal_proof(self):
        report = m.run(
            [
                {"tool": "delete", "input": {}},
                {"tool": "total", "input": {"values": [1, -2, 4]}},
                {"tool": "finish", "input": {}},
            ]
        )
        self.assertEqual(report["results"], [3])
        self.assertEqual(report["attempts"], 3)
        self.assertEqual(report["stop"], "requested-finish")
        self.assertNotIn("goal_reached", report)
        self.assertEqual(
            [x["outcome"] for x in report["trace"]],
            ["denied", "executed", "finish-request"],
        )

    def test_strict_arguments_reject_instead_of_clamp_and_do_not_mutate(self):
        values = [True, 1.5, math.inf, math.nan, 1000001, -(1000001), "4"]
        for value in values:
            request = {"tool": "total", "input": {"values": [value]}}
            report = m.run([request])
            self.assertEqual(report["results"], [])
            self.assertEqual(report["trace"][0]["outcome"], "invalid-arguments")
        request = {"tool": "total", "input": {"values": [1, 2]}}
        before = copy.deepcopy(request)
        self.assertEqual(m.run([request])["results"], [3])
        self.assertEqual(request, before)
        for args in [
            {"values": []},
            {"values": [0] * 17},
            {"values": [1], "approval": "APPROVED"},
        ]:
            self.assertEqual(m.run([{"tool": "total", "input": args}])["results"], [])

    def test_approval_text_is_not_a_grant(self):
        for request in [
            {"tool": "delete", "input": {"approval": "APPROVED"}},
            {"tool": "total", "input": {"values": [1]}, "approval": "APPROVED"},
        ]:
            self.assertEqual(m.run([request])["results"], [])

    def test_empty_exact_budget_and_exhaustion_are_distinct(self):
        self.assertEqual(
            m.run([]),
            {"attempts": 0, "stop": "input-exhausted", "results": [], "trace": []},
        )
        request = {"tool": "total", "input": {"values": [0]}}
        self.assertEqual(m.run([request], 1)["stop"], "budget")
        self.assertEqual(m.run([request], 2)["stop"], "input-exhausted")
        for budget in [True, 0, -1, 33, 1.5, "4"]:
            with self.assertRaises(ValueError):
                m.run([], budget)

    def test_provider_errors_propagate_without_success_report(self):
        def broken():
            yield {"tool": "total", "input": {"values": [1]}}
            raise OSError("provider failed")

        with self.assertRaises(OSError):
            m.run(broken())
