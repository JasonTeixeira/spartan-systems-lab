"""Unit tests for Spartan Blind War-Room, Boss-Fight signed receipts, and 15 SQL drills."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drills.sql.run_sql_drills import SQL_DRILLS, list_drills
from tools.war_room import (
    CHAOS_FAULTS,
    compute_receipt_sha256,
    run_boss_fight,
    start_war_room,
    verify_receipt_signature,
    verify_war_room,
)


def test_ten_unique_chaos_faults_defined() -> None:
    assert len(CHAOS_FAULTS) == 10
    ids = [f.id for f in CHAOS_FAULTS]
    assert len(set(ids)) == 10
    for fault in CHAOS_FAULTS:
        assert fault.symptom.startswith(("P1 ALERT", "P2 ALERT"))
        assert fault.remediation_hint


def test_blind_war_room_hides_fault_until_verified(tmp_path: Path) -> None:
    state_file = tmp_path / "war_room_active.json"
    started = start_war_room(dry_run=True, seed=42, state_file=state_file)
    assert started["status"] == "armed"
    assert "faultId" not in started
    assert started["symptom"].startswith(("P1", "P2"))
    assert state_file.exists()

    verified = verify_war_room(dry_run=True, state_file=state_file)
    assert verified["passed"] is True
    assert verified["revealedFault"] in {f.id for f in CHAOS_FAULTS}
    assert not state_file.exists()


def test_boss_fight_writes_signed_receipt_and_syncs_archos(tmp_path: Path) -> None:
    out_dir = tmp_path / "bench-receipts"
    archos_dir = tmp_path / "archos-receipts"
    res = run_boss_fight(
        "M01",
        dry_run=True,
        output_dir=out_dir,
        archos_receipts_dir=archos_dir,
    )
    receipt = res["receipt"]
    assert receipt["module"] == "M01"
    assert receipt["passed"] is True
    assert verify_receipt_signature(receipt) is True

    # Tampering must invalidate signature
    tampered = dict(receipt, module="M12")
    assert verify_receipt_signature(tampered) is False
    assert compute_receipt_sha256(receipt) == receipt["sha256"]

    # Both local benchmark receipt and synced ArchOS receipt exist and match
    bench_file = out_dir / "M01-latest.json"
    archos_file = archos_dir / "M01-latest.json"
    assert bench_file.exists()
    assert archos_file.exists()
    assert json.loads(bench_file.read_text(encoding="utf-8")) == receipt
    assert json.loads(archos_file.read_text(encoding="utf-8")) == receipt


def test_boss_fight_rejects_invalid_module(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Module must be one of"):
        run_boss_fight("M99", dry_run=True, output_dir=tmp_path)


def test_fifteen_sql_drills_catalog_complete() -> None:
    assert len(SQL_DRILLS) == 15
    items = list_drills()
    assert len({item["id"] for item in items}) == 15
    for item in items:
        assert item["verify_sql"].strip().endswith(";")
