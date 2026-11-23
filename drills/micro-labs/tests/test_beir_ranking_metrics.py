"""Hand-calculated scoring checks, not evidence of a retrieval reproduction."""

import copy
import importlib.util
import math
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "labs/beir-ranking/metrics.py"
SPEC = importlib.util.spec_from_file_location("owned_beir_metrics", PATH)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class RankingMetricTests(unittest.TestCase):
    def evaluate(self, rankings=None, qrels=None, k=10):
        return M.evaluate(
            ["q1", "q2"],
            ["a", "b", "c"],
            qrels or {"q1": {"a": 2, "b": 1}, "q2": {"c": 1}},
            rankings or {"q1": ["b", "a"], "q2": []},
            k,
        )

    def test_linear_trec_gain_not_exponential(self):
        actual = self.evaluate()["per_query"]["q1"]
        expected = (1 + 2 / math.log2(3)) / (2 + 1 / math.log2(3))
        self.assertAlmostEqual(actual, expected)
        exponential = (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3))
        self.assertNotAlmostEqual(actual, exponential)

    def test_empty_result_retained_in_macro_denominator(self):
        result = self.evaluate()
        self.assertEqual(result["queries"], 2)
        self.assertEqual(result["empty_rankings"], 1)
        self.assertEqual(result["per_query"]["q2"], 0)
        self.assertAlmostEqual(result["mean_ndcg"], result["per_query"]["q1"] / 2)

    def test_ideal_uses_all_judgments_not_retrieved_subset(self):
        result = self.evaluate({"q1": ["b"], "q2": []}, k=1)
        self.assertEqual(result["per_query"]["q1"], 0.5)

    def test_perfect_order_and_unjudged_zero(self):
        result = self.evaluate({"q1": ["a", "b"], "q2": ["a", "c"]})
        self.assertEqual(result["per_query"]["q1"], 1)
        self.assertAlmostEqual(result["per_query"]["q2"], 1 / math.log2(3))

    def test_missing_query_is_not_silently_dropped(self):
        for rankings in [{"q1": ["a"]}, {"q1": [], "q2": [], "extra": []}]:
            with self.assertRaises(ValueError):
                self.evaluate(rankings)

    def test_unknown_and_duplicate_documents_rejected(self):
        for ranking in [["a", "a"], ["not-in-corpus"], "abc"]:
            with self.assertRaises(ValueError):
                self.evaluate({"q1": ranking, "q2": []})

    def test_bad_grades_and_cutoffs_rejected(self):
        for grade in [True, -1, 1.5, "1", float("nan")]:
            with self.assertRaises(ValueError):
                self.evaluate(qrels={"q1": {"a": grade}, "q2": {"c": 1}})
        for k in [True, 0, 1001, 1.5]:
            with self.assertRaises(ValueError):
                self.evaluate(k=k)

    def test_query_and_corpus_identity_checks(self):
        for queries, corpus in [
            (["q1", "q1"], ["a"]),
            ([], ["a"]),
            (["q1"], ["a", "a"]),
            (["q1"], []),
        ]:
            with self.assertRaises(ValueError):
                M.evaluate(queries, corpus, {"q1": {"a": 1}}, {"q1": ["a"]})
        with self.assertRaises(ValueError):
            self.evaluate(qrels={"q1": {"unknown": 1}, "q2": {"c": 1}})

    def test_zero_ideal_has_declared_zero_score(self):
        result = self.evaluate(qrels={"q1": {"a": 0}, "q2": {}})
        self.assertEqual(result["mean_ndcg"], 0)

    def test_scorer_does_not_change_rankings_or_labels(self):
        rankings = {"q1": ["b", "a"], "q2": []}
        qrels = {"q1": {"a": 2}, "q2": {"c": 1}}
        before = copy.deepcopy((rankings, qrels))
        self.evaluate(rankings, qrels)
        self.assertEqual((rankings, qrels), before)


if __name__ == "__main__":
    unittest.main()
