import copy
import importlib.util
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "labs/credential-leak/scanner.py"
scanner = None
if PATH.exists():
    spec = importlib.util.spec_from_file_location("credential_leak_scanner", PATH)
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)


class CredentialLeakTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(scanner, "The C03 local scanner is missing.")
        self.unsafe = scanner.read_fixture(PATH.parent / "fixtures/unsafe.json")
        self.repaired = scanner.read_fixture(PATH.parent / "fixtures/repaired.json")

    def test_planted_values_are_detected_in_the_expected_surfaces_without_echoing_them(self):
        report = scanner.scan_fixture(self.unsafe)
        self.assertEqual(report["status"], "findings")
        self.assertEqual(report["scanned_events"], 4)
        self.assertEqual({row["surface"] for row in report["findings"]}, {"log", "prompt"})
        self.assertEqual(sum(row["matches"] for row in report["findings"]), 2)
        encoded = json.dumps(report)
        self.assertNotIn("TRAINING_CREDENTIAL_", encoded)
        self.assertNotIn(self.unsafe["events"][1]["text"], encoded)

    def test_detection_uses_content_not_a_known_event_id_or_a_fixed_answer(self):
        data = copy.deepcopy(self.repaired)
        data["events"] = [
            {
                "id": "changed-event",
                "surface": "output",
                "text": "Unexpected value: TRAINING_CREDENTIAL_1234ABCD5678",
            }
        ]
        report = scanner.scan_fixture(data)
        self.assertEqual(report["status"], "findings")
        self.assertEqual(report["findings"][0]["event_id"], "changed-event")
        data["events"][0]["text"] = "A documented placeholder, not a matching marker."
        self.assertEqual(scanner.scan_fixture(data)["status"], "clean")

    def test_redaction_preserves_records_and_input_and_matches_the_repaired_fixture(self):
        before = copy.deepcopy(self.unsafe)
        repaired = scanner.redact_fixture(self.unsafe)
        self.assertEqual(self.unsafe, before)
        self.assertEqual(repaired["events"], self.repaired["events"])
        self.assertEqual([x["id"] for x in repaired["events"]], [x["id"] for x in before["events"]])
        report = scanner.scan_fixture(repaired)
        self.assertEqual(report["status"], "clean")
        self.assertEqual(report["scanned_events"], 4)

    def test_zero_records_malformed_shapes_and_unreported_fields_fail_closed(self):
        for mutate in [
            lambda x: x.update(events=[]),
            lambda x: x.update(events="wrong type"),
            lambda x: x.update(schema_version=True),
            lambda x: x.update(unscanned_text="hidden"),
            lambda x: x["events"][0].update(surface="unknown"),
            lambda x: x["events"][0].update(text=None),
            lambda x: x["events"][0].update(extra="unscanned"),
            lambda x: x["events"][1].update(id=x["events"][0]["id"]),
            lambda x: x["events"][0].update(id="TRAINING_CREDENTIAL_ABCD1234EFGH"),
        ]:
            bad = copy.deepcopy(self.unsafe)
            mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                scanner.scan_fixture(bad)

    def test_size_limits_and_invalid_json_are_errors_not_clean_results(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "fixture.json"
            for raw in [
                b'{"events":',
                b"\xff",
                b"x" * (scanner.MAX_INPUT_BYTES + 1),
                b'{"schema_version":1,"schema_version":1,"fixture_id":"duplicate","events":[]}',
            ]:
                p.write_bytes(raw)
                with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                    scanner.read_fixture(p)
            p.write_text(json.dumps(self.repaired))
            alias = p.parent / "alias.json"
            alias.symlink_to(p)
            with self.assertRaises(ValueError):
                scanner.read_fixture(alias)

    def test_event_count_and_text_size_limits_are_enforced(self):
        for bad in [
            dict(self.unsafe, events=self.unsafe["events"] * (scanner.MAX_EVENTS + 1)),
            {
                "schema_version": 1,
                "fixture_id": "too-long",
                "events": [
                    {"id": "one", "surface": "log", "text": "x" * (scanner.MAX_TEXT_BYTES + 1)}
                ],
            },
        ]:
            with self.assertRaises(ValueError):
                scanner.scan_fixture(bad)

    def test_cli_exit_codes_distinguish_findings_clean_and_errors(self):
        for fixture, expected_code, status in [
            ("unsafe", 1, "findings"),
            ("repaired", 0, "clean"),
            ("invalid", 2, "error"),
        ]:
            with self.subTest(fixture=fixture):
                result = subprocess.run(
                    [sys.executable, str(PATH), "--fixture", fixture],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], status)
                self.assertNotIn("TRAINING_CREDENTIAL_", result.stdout + result.stderr)
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(scanner.main(["--fixture", fixture]), expected_code)

    def test_missing_input_is_error_and_self_check_checks_the_failure_before_the_repair(self):
        output = io.StringIO()
        with patch.object(scanner, "FIXTURES", ROOT / "does-not-exist"), redirect_stdout(output):
            self.assertEqual(scanner.main(["--fixture", "unsafe"]), 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "error")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(scanner.main(["--self-check"]), 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report["passed"])
        self.assertTrue(all(check["passed"] for check in report["checks"]))

    def test_shell_suppression_can_hide_a_real_finding_but_direct_command_does_not(self):
        command = [sys.executable, str(PATH), "--fixture", "unsafe"]
        direct = subprocess.run(command, capture_output=True, text=True)
        masked = subprocess.run(
            ["/bin/sh", "-c", shlex.join(command) + " || true"], capture_output=True, text=True
        )
        self.assertEqual(direct.returncode, 1)
        self.assertEqual(masked.returncode, 0)
        self.assertEqual(json.loads(direct.stdout)["status"], "findings")
        self.assertEqual(json.loads(masked.stdout)["status"], "findings")

    def test_cli_error_handling_does_not_echo_exception_details_or_values(self):
        output = io.StringIO()
        with (
            patch.object(
                scanner,
                "read_fixture",
                side_effect=ValueError("untrusted content TRAINING_CREDENTIAL_ABCD1234EFGH"),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(scanner.main(["--fixture", "unsafe"]), 2)
        self.assertNotIn("TRAINING_CREDENTIAL_", output.getvalue())
        self.assertNotIn("untrusted content", output.getvalue())

    def test_published_exercise_contract_matches_real_process_outcomes(self):
        contract = json.loads(
            (ROOT / "teaching/security/credential-leak/exercise.json").read_text()
        )
        self.assertEqual(contract["edition_id"], "credential-leak-v1")
        self.assertEqual(contract["finding_id"], "C03")
        self.assertEqual(
            {case["fixture"] for case in contract["cases"]}, {"unsafe", "repaired", "invalid"}
        )
        for case in contract["cases"]:
            result = subprocess.run(
                [sys.executable, str(PATH), "--fixture", case["fixture"]],
                capture_output=True,
                text=True,
            )
            report = json.loads(result.stdout)
            with self.subTest(fixture=case["fixture"]):
                self.assertEqual(result.returncode, case["exit_code"])
                self.assertEqual(report["status"], case["status"])
                if case["status"] != "error":
                    self.assertEqual(report["scanned_events"], case["scanned_events"])
                    self.assertEqual(sum(x["matches"] for x in report["findings"]), case["matches"])


if __name__ == "__main__":
    unittest.main()
