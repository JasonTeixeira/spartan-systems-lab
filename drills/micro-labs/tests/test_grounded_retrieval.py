import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "labs/grounded-retrieval/system.py"
lab = None
if PATH.exists():
    spec = importlib.util.spec_from_file_location("grounded_retrieval", PATH)
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)


class GroundedRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(lab, "The C04 source-based retrieval pipeline is missing.")
        self.corpus = lab.read_corpus(PATH.parent / "corpus.json")
        self.question = "What is the retention period for Atlas?"

    def test_retrieval_computes_scores_from_text_and_changes_when_source_changes(self):
        hits = lab.retrieve(self.question, self.corpus, k=3)
        self.assertEqual(hits[0]["chunk_id"], "atlas-policy:L1")
        self.assertGreater(hits[0]["score"], hits[1]["score"])
        changed = copy.deepcopy(self.corpus)
        changed["documents"][0]["text"] = "Unrelated archive statement."
        self.assertNotEqual(
            lab.retrieve(self.question, changed, k=3)[0]["chunk_id"], hits[0]["chunk_id"]
        )
        bad = copy.deepcopy(self.corpus)
        bad["documents"][0]["score"] = 1.0
        with self.assertRaises(ValueError):
            lab.retrieve(self.question, bad, k=3)

    def test_cosine_scores_zero_overlap_and_ties_have_a_defined_order(self):
        corpus = {
            "schema_version": 1,
            "documents": [
                {"id": "z", "text": "Atlas retention period."},
                {"id": "a", "text": "Atlas retention period."},
                {"id": "none", "text": "Ocean tide."},
            ],
        }
        hits = lab.retrieve("Atlas retention period", corpus, k=3)
        self.assertEqual([h["chunk_id"] for h in hits], ["a:L1", "z:L1", "none:L1"])
        self.assertAlmostEqual(hits[0]["score"], 1.0)
        self.assertEqual(hits[2]["score"], 0.0)

    def test_answer_is_an_exact_quote_with_resolvable_retrieved_source_span(self):
        report = lab.answer(self.question, self.corpus)
        self.assertEqual(report["action"], "answer")
        self.assertEqual(report["claims"][0]["text"], "Atlas retention period is 30 days.")
        citation = report["claims"][0]["citation"]
        document = next(d for d in self.corpus["documents"] if d["id"] == citation["document_id"])
        self.assertEqual(
            document["text"][citation["start"] : citation["end"]], report["claims"][0]["text"]
        )
        self.assertTrue(
            lab.verify_claim(report["claims"][0], self.question, self.corpus, report["context"])
        )
        self.assertEqual(report["exact_support_rate"], 1.0)
        self.assertIn("[atlas-policy:0:34]", report["answer"])

    def test_changed_questions_retrieve_different_entities_and_attributes(self):
        for question, expected in [
            ("What is the retention period for Beacon?", "Beacon retention period is 7 days."),
            ("What is the storage region for Atlas?", "Atlas storage region is north-1."),
            ("What is simulation mode for Meridian?", "Meridian simulation mode is paper-only."),
        ]:
            with self.subTest(question=question):
                report = lab.answer(question, self.corpus)
                self.assertEqual(report["action"], "answer")
                self.assertEqual(report["claims"][0]["text"], expected)

    def test_changed_source_value_changes_answer_without_changing_a_label(self):
        changed = copy.deepcopy(self.corpus)
        changed["documents"][0]["text"] = changed["documents"][0]["text"].replace(
            "30 days", "45 days"
        )
        report = lab.answer(self.question, changed)
        self.assertEqual(report["claims"][0]["text"], "Atlas retention period is 45 days.")
        self.assertTrue(
            lab.verify_claim(report["claims"][0], self.question, changed, report["context"])
        )

    def test_missing_evidence_refuses_even_when_similarity_clears_threshold(self):
        missing = copy.deepcopy(self.corpus)
        missing["documents"] = [d for d in missing["documents"] if d["id"] != "atlas-policy"]
        report = lab.answer(self.question, missing)
        self.assertGreaterEqual(report["retrieved"][0]["score"], report["threshold"])
        self.assertEqual(report["action"], "refuse")
        self.assertEqual(report["reason"], "no_matching_fact")
        self.assertEqual(report["claims"], [])
        self.assertIsNone(report["exact_support_rate"])
        missing["documents"] = []
        self.assertEqual(lab.answer(self.question, missing)["reason"], "no_retrieval_support")

    def test_conflicting_retrieved_values_refuse_instead_of_selecting_one(self):
        changed = copy.deepcopy(self.corpus)
        changed["documents"].append(
            {"id": "conflict", "text": "Atlas retention period is 90 days."}
        )
        report = lab.answer(self.question, changed, k=10)
        self.assertEqual(report["action"], "refuse")
        self.assertEqual(report["reason"], "conflicting_sources")

    def test_case_distinct_fact_values_are_conflicts_not_assumed_equivalent(self):
        corpus = {
            "schema_version": 1,
            "documents": [
                {"id": "upper", "text": "Atlas code is AbC."},
                {"id": "lower", "text": "Atlas code is abc."},
            ],
        }
        report = lab.answer("What is code for Atlas?", corpus)
        self.assertEqual(report["action"], "refuse")
        self.assertEqual(report["reason"], "conflicting_sources")
        corpus["documents"][1]["text"] = "Atlas code is AbC."
        self.assertEqual(lab.answer("What is code for Atlas?", corpus)["action"], "answer")

    def test_a_threshold_alone_cannot_answer_a_missing_attribute_or_question_form(self):
        report = lab.answer("What is the trading fee for Atlas?", self.corpus, threshold=0.01)
        self.assertEqual(report["action"], "refuse")
        self.assertEqual(report["reason"], "no_matching_fact")
        report = lab.answer("Recommend the most profitable strategy.", self.corpus)
        self.assertEqual(report["reason"], "unsupported_question_form")

    def test_verifier_rejects_invented_text_bad_spans_irrelevant_or_unretrieved_quotes(self):
        report = lab.answer(self.question, self.corpus)
        valid = report["claims"][0]
        for mutate in [
            lambda x: x.update(text="Atlas retention period is 300 days."),
            lambda x: x["citation"].update(document_id="missing"),
            lambda x: x["citation"].update(start=-1),
            lambda x: x["citation"].update(start=False),
            lambda x: x["citation"].update(end=999999),
            lambda x: x.update(ok=True),
        ]:
            claim = copy.deepcopy(valid)
            mutate(claim)
            with self.subTest(mutate=mutate):
                self.assertFalse(
                    lab.verify_claim(claim, self.question, self.corpus, report["context"])
                )
        self.assertFalse(lab.verify_claim(valid, self.question, self.corpus, []))
        self.assertFalse(
            lab.verify_claim(
                valid, "What is storage region for Atlas?", self.corpus, report["context"]
            )
        )

    def test_unsupported_composer_output_is_blocked_by_the_integrated_pipeline(self):
        bad = {
            "text": "Atlas retention period is 300 days.",
            "citation": {"document_id": "atlas-policy", "start": 0, "end": 34},
        }
        with patch.object(lab, "compose", return_value=[bad]):
            report = lab.answer(self.question, self.corpus)
        self.assertEqual(report["action"], "refuse")
        self.assertEqual(report["reason"], "unsupported_generated_claim")
        self.assertEqual(report["exact_support_rate"], 0.0)
        self.assertEqual(report["claims"], [])

    def test_recall_uses_separate_annotations_not_answer_inputs_and_empty_gold_is_undefined(self):
        report = lab.answer(self.question, self.corpus)
        self.assertEqual(lab.recall_at_k(report, ["atlas-policy:L1"]), 1.0)
        self.assertEqual(lab.recall_at_k(report, ["atlas-policy:L1", "absent:L1"]), 0.5)
        self.assertIsNone(lab.recall_at_k(report, []))
        self.assertEqual(lab.answer(self.question, self.corpus), report)
        with self.assertRaises(ValueError):
            lab.recall_at_k(report, ["atlas-policy:L1", "atlas-policy:L1"])

    def test_corpus_schema_limits_parameters_and_input_types_fail_explicitly(self):
        for mutate in [
            lambda x: x.update(schema_version=True),
            lambda x: x.update(ok=True),
            lambda x: x.update(documents="wrong"),
            lambda x: x["documents"][0].update(id="../escape"),
            lambda x: x["documents"][0].update(text=None),
            lambda x: x["documents"][0].update(text="x" * (lab.MAX_TEXT_BYTES + 1)),
            lambda x: x["documents"][1].update(id=x["documents"][0]["id"]),
        ]:
            changed = copy.deepcopy(self.corpus)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                lab.answer(self.question, changed)
        for kwargs in [
            {"k": 0},
            {"k": True},
            {"k": 21},
            {"threshold": float("nan")},
            {"threshold": float("inf")},
            {"threshold": 0},
            {"threshold": True},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                lab.answer(self.question, self.corpus, **kwargs)
        for question in [None, "", "x" * 501]:
            with self.subTest(question=question), self.assertRaises(ValueError):
                lab.answer(question, self.corpus)

    def test_malformed_duplicate_key_oversize_and_symlink_files_are_not_clean_results(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "corpus.json"
            for raw in [
                b"{",
                b"\xff",
                b"x" * (lab.MAX_INPUT_BYTES + 1),
                b'{"schema_version":1,"schema_version":1,"documents":[]}',
            ]:
                path.write_bytes(raw)
                with self.subTest(raw=raw[:10]), self.assertRaises(ValueError):
                    lab.read_corpus(path)
            path.write_text(json.dumps(self.corpus))
            alias = path.parent / "alias.json"
            alias.symlink_to(path)
            with self.assertRaises(ValueError):
                lab.read_corpus(alias)

    def test_pipeline_is_deterministic_and_does_not_modify_documents(self):
        before = copy.deepcopy(self.corpus)
        first = lab.answer(self.question, self.corpus)
        self.assertEqual(first, lab.answer(self.question, self.corpus))
        self.assertEqual(self.corpus, before)

    def test_small_k_can_miss_an_existing_fact_and_stricter_gate_can_refuse(self):
        corpus = copy.deepcopy(self.corpus)
        corpus["documents"].append({"id": "decoy", "text": "Atlas retention period"})
        missed = lab.answer(self.question, corpus, k=1)
        self.assertEqual(missed["reason"], "no_matching_fact")
        self.assertEqual(lab.recall_at_k(missed, ["atlas-policy:L1"]), 0.0)
        recovered = lab.answer(self.question, corpus, k=2)
        self.assertEqual(recovered["action"], "answer")
        self.assertEqual(lab.recall_at_k(recovered, ["atlas-policy:L1"]), 1.0)
        self.assertEqual(
            lab.answer(self.question, self.corpus, threshold=1.0)["reason"], "no_retrieval_support"
        )

    def test_citations_use_character_offsets_and_preserve_crlf_and_unicode_source(self):
        corpus = {
            "schema_version": 1,
            "documents": [
                {
                    "id": "unicode",
                    "text": "Fictional note 🧪.\r\nAtlas retention period is 30 days.",
                }
            ],
        }
        report = lab.answer(self.question, corpus)
        claim = report["claims"][0]
        self.assertEqual(claim["citation"]["start"], len("Fictional note 🧪.\r\n"))
        self.assertTrue(lab.verify_claim(claim, self.question, corpus, report["context"]))

    def test_document_and_chunk_count_limits_are_enforced(self):
        for corpus in [
            {
                "schema_version": 1,
                "documents": [
                    {"id": f"doc-{i}", "text": "Fictional."} for i in range(lab.MAX_DOCUMENTS + 1)
                ],
            },
            {
                "schema_version": 1,
                "documents": [{"id": "lines", "text": "Line.\n" * (lab.MAX_CHUNKS + 1)}],
            },
        ]:
            with self.assertRaises(ValueError):
                lab.answer(self.question, corpus)

    def test_real_cli_answers_refuses_and_reports_errors_with_distinct_exits(self):
        for args, code, key, value in [
            ([], 0, "action", "answer"),
            (["--question", "What is trading fee for Atlas?"], 1, "action", "refuse"),
            (["--threshold", "nan"], 2, "status", "error"),
        ]:
            result = subprocess.run(
                [sys.executable, str(PATH), *args], capture_output=True, text=True
            )
            with self.subTest(args=args):
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(json.loads(result.stdout)[key], value)
        output = io.StringIO()
        with patch.object(lab, "CORPUS", ROOT / "missing-corpus.json"), redirect_stdout(output):
            self.assertEqual(lab.main([]), 2)
        self.assertNotIn(str(ROOT), output.getvalue())

    def test_published_cases_are_assessment_only_and_self_check_reports_actual_metrics(self):
        contract = json.loads((ROOT / "teaching/ai/grounded-retrieval/exercise.json").read_text())
        self.assertEqual(contract["edition_id"], "grounded-retrieval-v1")
        self.assertEqual(contract["finding_id"], "C04")
        self.assertNotIn("relevant", self.corpus)
        for case in contract["cases"]:
            report = lab.answer(case["question"], self.corpus)
            with self.subTest(case=case["id"]):
                self.assertEqual(report["action"], case["expected_action"])
                self.assertEqual(report["reason"], case["expected_reason"])
                self.assertEqual([x["text"] for x in report["claims"]], case["expected_claims"])
                self.assertEqual(
                    lab.recall_at_k(report, case["relevant_chunk_ids"]),
                    case["expected_recall_at_k"],
                )
        result = subprocess.run(
            [sys.executable, str(PATH), "--self-check"], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])


if __name__ == "__main__":
    unittest.main()
