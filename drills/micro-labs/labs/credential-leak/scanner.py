"""C03 training fixture: detect synthetic credential markers without echoing them.

No repository traversal, environment reads, network, credential validity checks,
input-file writes or submitted-source execution. This is not a production scanner.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MAX_INPUT_BYTES = 65_536
MAX_EVENTS = 50
MAX_TEXT_BYTES = 8192
MARKER = re.compile(r"\bTRAINING_CREDENTIAL_[A-Z0-9]{12,32}\b")
IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,47}")
SURFACES = {"log", "prompt", "output"}


def validate_fixture(data: dict) -> None:
    if not isinstance(data, dict) or set(data) != {"schema_version", "fixture_id", "events"}:
        raise ValueError("Invalid fixture schema.")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported fixture schema.")
    if not isinstance(data["fixture_id"], str) or not IDENTIFIER.fullmatch(data["fixture_id"]):
        raise ValueError("Invalid fixture identifier.")
    events = data["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise ValueError("Invalid event collection.")
    seen = set()
    for event in events:
        if not isinstance(event, dict) or set(event) != {"id", "surface", "text"}:
            raise ValueError("Invalid event schema.")
        event_id = event["id"]
        if not isinstance(event_id, str) or not IDENTIFIER.fullmatch(event_id) or event_id in seen:
            raise ValueError("Invalid or duplicate event identifier.")
        if not isinstance(event["surface"], str) or event["surface"] not in SURFACES:
            raise ValueError("Unsupported event surface.")
        if (
            not isinstance(event["text"], str)
            or len(event["text"].encode("utf-8")) > MAX_TEXT_BYTES
        ):
            raise ValueError("Invalid event text.")
        seen.add(event_id)


def unique_object(pairs: list[tuple]) -> dict:
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("Duplicate fixture field.")
        data[key] = value
    return data


def read_fixture(path: Path) -> dict:
    """Read one bounded regular file. The CLI selects only named lab fixtures."""
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Invalid fixture file.")
        with path.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Fixture size limit exceeded.")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        validate_fixture(data)
        return data
    except (OSError, ValueError) as error:
        raise ValueError("Fixture could not be read or validated.") from error


def scan_fixture(data: dict) -> dict:
    validate_fixture(data)
    findings = []
    for event in data["events"]:
        matches = sum(1 for _ in MARKER.finditer(event["text"]))
        if matches:
            findings.append(
                {
                    "event_id": event["id"],
                    "surface": event["surface"],
                    "rule": "synthetic-credential-v1",
                    "matches": matches,
                }
            )
    return {
        "status": "findings" if findings else "clean",
        "scanned_events": len(data["events"]),
        "findings": findings,
        "scope": "Synthetic training markers in the supplied event text fields only.",
    }


def redact_fixture(data: dict) -> dict:
    """Model a producer-side repair as a new object; never alter stored input."""
    validate_fixture(data)
    return {
        "schema_version": data["schema_version"],
        "fixture_id": data["fixture_id"],
        "events": [
            dict(event, text=MARKER.sub("[REDACTED]", event["text"])) for event in data["events"]
        ],
    }


def self_check() -> dict:
    unsafe = read_fixture(FIXTURES / "unsafe.json")
    repaired = read_fixture(FIXTURES / "repaired.json")
    before = json.dumps(unsafe, sort_keys=True)
    positive = scan_fixture(unsafe)
    negative = scan_fixture(repaired)
    modeled = redact_fixture(unsafe)
    encoded = json.dumps({"unsafe": positive, "repaired": negative})
    checks = [
        {
            "name": "planted markers detected",
            "passed": sum(x["matches"] for x in positive["findings"]) == 2,
        },
        {
            "name": "repaired fixture has no matching markers",
            "passed": negative["status"] == "clean",
        },
        {
            "name": "repair preserves the same four events",
            "passed": len(unsafe["events"]) == len(repaired["events"]) == 4
            and modeled["events"] == repaired["events"],
        },
        {
            "name": "source input is unchanged",
            "passed": json.dumps(unsafe, sort_keys=True) == before,
        },
        {
            "name": "reports omit marker values and prefix",
            "passed": "TRAINING_CREDENTIAL_" not in encoded,
        },
    ]
    return {"status": "self-check", "passed": all(x["passed"] for x in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--fixture", choices=["unsafe", "repaired", "invalid"], default="unsafe")
    options.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.self_check:
            report = self_check()
            code = 0 if report["passed"] else 1
        else:
            report = scan_fixture(read_fixture(FIXTURES / f"{args.fixture}.json"))
            code = 1 if report["status"] == "findings" else 0
    except Exception:
        # Preserve a nonzero failure without echoing fixture content or exception details.
        report = {
            "status": "error",
            "code": "invalid-or-unreadable-fixture",
            "scope": "No clean result was established.",
        }
        code = 2
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
