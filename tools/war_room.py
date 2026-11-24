"""
Spartan Blind Chaos War-Room & Automated Boss-Fight Receipt Engine.

Provides:
  1. `start`       - Blind Chaos Roulette: injects 1 of 10 real production faults
                     without revealing its name, records start timestamp, and prints
                     only the PagerDuty symptom.
  2. `verify`      - Automated SLA Verifier: probes Edge HTTP 200, latency, and
                     Postgres lock health; computes MTTR and reveals the root cause
                     only after recovery passes.
  3. `boss-fight`  - Runs module verification gates (M01-M12), generates a signed
                     SHA-256 Lab-Proven JSON receipt, writes to docs/benchmarks/receipts/,
                     and optionally syncs to ArchOS via --archos-receipts-dir or
                     ARCHOS_RECEIPTS_DIR env var.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAOS_SCRIPT = REPO_ROOT / "lab-1-core-engine" / "scripts" / "chaos_lab1.sh"
STATE_FILE = REPO_ROOT / ".local" / "war_room_active.json"
DEFAULT_RECEIPTS_DIR = REPO_ROOT / "docs" / "benchmarks" / "receipts"


@dataclass(frozen=True)
class ChaosFault:
    id: str
    symptom: str
    category: str
    remediation_hint: str


CHAOS_FAULTS: tuple[ChaosFault, ...] = (
    ChaosFault(
        id="lock-storm",
        symptom=(
            "P1 ALERT: Write/read queries against `events` are stalled (>15s); "
            "API workers queuing."
        ),
        category="postgres-locks",
        remediation_hint=(
            "Inspect pg_stat_activity & pg_locks for ACCESS EXCLUSIVE holder "
            "and terminate blocker."
        ),
    ),
    ChaosFault(
        id="net-latency",
        symptom=(
            "P1 ALERT: Edge-to-toolbox p99 latency jumped >250ms "
            "with intermittent packet drops."
        ),
        category="network",
        remediation_hint=(
            "Inspect `tc qdisc show dev eth0` inside sre-toolbox and remove netem rule."
        ),
    ),
    ChaosFault(
        id="idle-in-tx",
        symptom="P1 ALERT: Tenant row updates timing out while CPU stays near 0%.",
        category="postgres-locks",
        remediation_hint=(
            "Query pg_stat_activity WHERE state = 'idle in transaction' and "
            "terminate/configure idle_in_transaction_session_timeout."
        ),
    ),
    ChaosFault(
        id="pool-exhaustion",
        symptom="P1 ALERT: API returning 503/timeouts waiting for DB connection slots.",
        category="connection-pool",
        remediation_hint=(
            "Check PgBouncer pool saturation and terminate long pg_sleep backends."
        ),
    ),
    ChaosFault(
        id="redis-flush-stampede",
        symptom=(
            "P2 ALERT: Cache hit ratio collapsed to 0%; "
            "Postgres CPU & read IOPS spiked."
        ),
        category="caching",
        remediation_hint=(
            "Verify Redis keyspace (`INFO keyspace`), warm critical keys, "
            "and apply singleflight/jitter TTL."
        ),
    ),
    ChaosFault(
        id="nginx-bad-upstream",
        symptom="P1 ALERT: Edge Nginx returning HTTP 502/504 Bad Gateway on /healthz.",
        category="edge-proxy",
        remediation_hint=(
            "Check container state (`docker ps -a`) and unpause/restart `spartan-api`."
        ),
    ),
    ChaosFault(
        id="seq-scan-bloat",
        symptom=(
            "P1 ALERT: Point lookups on `events` degraded from 2ms to >300ms "
            "despite low traffic."
        ),
        category="query-planner",
        remediation_hint=(
            "Run EXPLAIN (ANALYZE, BUFFERS) + `SHOW enable_indexscan`; "
            "reset database planner settings."
        ),
    ),
    ChaosFault(
        id="cpu-burn",
        symptom=(
            "P2 ALERT: sre-toolbox host load average > 2.0 "
            "and user CPU pegged near 100%."
        ),
        category="linux-cpu",
        remediation_hint=(
            "Run `mpstat -P ALL 1 2` and `ps aux --sort=-%cpu` to kill runaway workers."
        ),
    ),
    ChaosFault(
        id="timeout-mismatch",
        symptom=(
            "P1 ALERT: Normal SQL summary queries aborting with "
            "`canceling statement due to statement timeout`."
        ),
        category="postgres-config",
        remediation_hint=(
            "Check `SHOW statement_timeout` and "
            "`ALTER DATABASE spartan_lab RESET statement_timeout`."
        ),
    ),
    ChaosFault(
        id="disk-fill",
        symptom="P2 ALERT: Disk usage alert fired on sre-toolbox `/tmp` filesystem.",
        category="linux-storage",
        remediation_hint=(
            "Run `df -h` and `du -sh /tmp/*` inside sre-toolbox and "
            "remove orphaned large artifacts."
        ),
    ),
)

VALID_MODULES: tuple[str, ...] = tuple(f"M{i:02d}" for i in range(1, 13))


def compute_receipt_sha256(payload: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hex digest over a receipt payload (excluding sha256)."""
    clean = {k: v for k, v in payload.items() if k != "sha256"}
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def verify_receipt_signature(payload: dict[str, Any]) -> bool:
    """Return True if the receipt carries a valid deterministic SHA-256 digest."""
    expected = payload.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    return compute_receipt_sha256(payload) == expected


def select_blind_fault(seed: int | None = None, fault_id: str | None = None) -> ChaosFault:
    if fault_id is not None:
        for fault in CHAOS_FAULTS:
            if fault.id == fault_id:
                return fault
        raise ValueError(f"Unknown chaos fault id: {fault_id}")
    rng = random.Random(seed)
    return rng.choice(CHAOS_FAULTS)


def start_war_room(
    *,
    dry_run: bool = False,
    seed: int | None = None,
    fault_id: str | None = None,
    state_file: Path = STATE_FILE,
) -> dict[str, Any]:
    fault = select_blind_fault(seed=seed, fault_id=fault_id)
    started_at = datetime.now(UTC).isoformat()
    state = {
        "faultId": fault.id,
        "category": fault.category,
        "symptom": fault.symptom,
        "remediationHint": fault.remediation_hint,
        "startedAt": started_at,
        "startedEpoch": time.time(),
        "dryRun": dry_run,
    }
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if not dry_run:
        subprocess.run(["bash", str(CHAOS_SCRIPT), fault.id], check=False)

    return {
        "status": "armed",
        "startedAt": started_at,
        "symptom": fault.symptom,
        "dryRun": dry_run,
        "nextStep": "Diagnose & fix live, then run: make war-room-verify",
    }


def _probe_http_health(
    url: str, attempts: int = 5, timeout_s: float = 2.0
) -> tuple[bool, float, int]:
    latencies_ms: list[float] = []
    errors_5xx = 0
    for _ in range(attempts):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:
                code = int(resp.status)
                latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                if code >= 500 or code != 200:
                    errors_5xx += 1
        except (urllib.error.URLError, TimeoutError, OSError):
            errors_5xx += 1
            latencies_ms.append(timeout_s * 1000.0)
    p99_ms = max(latencies_ms) if latencies_ms else timeout_s * 1000.0
    return (errors_5xx == 0 and p99_ms < 250.0), round(p99_ms, 2), errors_5xx


def verify_war_room(
    *,
    dry_run: bool = False,
    health_url: str = "http://127.0.0.1:8080/healthz",
    state_file: Path = STATE_FILE,
) -> dict[str, Any]:
    if not state_file.exists():
        return {
            "passed": False,
            "error": "No active war-room session found. Start one with: make war-room",
        }
    state = json.loads(state_file.read_text(encoding="utf-8"))
    elapsed = max(0.0, round(time.time() - float(state.get("startedEpoch", time.time())), 2))

    if dry_run or state.get("dryRun"):
        checks = [
            {
                "name": "edge_http_200",
                "status": "pass",
                "detail": "dry-run SLA verified (p99=12.4ms, 0 5xx)",
            },
            {
                "name": "postgres_zero_blocked_locks",
                "status": "pass",
                "detail": "dry-run 0 blocked locks",
            },
        ]
        passed = True
    else:
        http_ok, p99_ms, errors_5xx = _probe_http_health(health_url)
        lock_cmd = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(REPO_ROOT / "lab-1-core-engine" / "docker-compose.yml"),
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "spartan",
                "-d",
                "spartan_lab",
                "-tAc",
                "SELECT count(*) FROM pg_locks WHERE NOT granted;",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        raw_locks = lock_cmd.stdout.strip()
        blocked_locks = int(raw_locks) if lock_cmd.returncode == 0 and raw_locks.isdigit() else -1
        locks_ok = blocked_locks == 0
        checks = [
            {
                "name": "edge_http_200",
                "status": "pass" if http_ok else "fail",
                "detail": f"p99={p99_ms}ms, errors_5xx={errors_5xx}",
            },
            {
                "name": "postgres_zero_blocked_locks",
                "status": "pass" if locks_ok else "fail",
                "detail": f"blocked_locks={blocked_locks}",
            },
        ]
        passed = http_ok and locks_ok

    result: dict[str, Any] = {
        "passed": passed,
        "elapsedSeconds": elapsed,
        "checks": checks,
    }
    if passed:
        result["revealedFault"] = state["faultId"]
        result["category"] = state["category"]
        result["remediationHint"] = state["remediationHint"]
        state_file.unlink(missing_ok=True)
    else:
        result["message"] = (
            "Outage NOT yet resolved. Keep diagnosing or run `make chaos SCENARIO=clear-all`."
        )
    return result


def run_boss_fight(
    module: str,
    *,
    dry_run: bool = False,
    output_dir: Path = DEFAULT_RECEIPTS_DIR,
    archos_receipts_dir: Path | None = None,
) -> dict[str, Any]:
    mod = module.upper()
    if mod not in VALID_MODULES:
        raise ValueError(
            f"Module must be one of {VALID_MODULES[0]}..{VALID_MODULES[-1]}, got '{module}'"
        )

    t0 = time.perf_counter()
    checks: list[dict[str, str]] = []

    if dry_run:
        checks = [
            {"name": "ruff_lint", "status": "pass", "detail": "dry-run"},
            {"name": "pytest_core", "status": "pass", "detail": "dry-run"},
            {"name": "micro_labs_contract", "status": "pass", "detail": "dry-run"},
        ]
        all_passed = True
    else:
        gate_cmds: list[tuple[str, list[str]]] = [
            ("ruff_lint", ["uv", "run", "ruff", "check", "."]),
            (
                "mypy_strict",
                ["uv", "run", "mypy", "lab-1-core-engine/app", "mcp_server", "tools", "tests"],
            ),
            ("pytest_core", ["uv", "run", "pytest", "tests/", "-q"]),
            ("micro_labs_contract", ["uv", "run", "pytest", "drills/micro-labs/tests/", "-q"]),
        ]
        all_passed = True
        for name, cmd in gate_cmds:
            proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
            ok = proc.returncode == 0
            if not ok:
                all_passed = False
            tail = (proc.stdout or proc.stderr or "").strip().splitlines()
            checks.append(
                {
                    "name": name,
                    "status": "pass" if ok else "fail",
                    "detail": tail[-1] if tail else f"exit={proc.returncode}",
                }
            )

    elapsed = round(time.perf_counter() - t0, 2)
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "module": mod,
        "passed": all_passed,
        "passedAt": datetime.now(UTC).isoformat(),
        "elapsedSeconds": elapsed,
        "checks": checks,
        "verifiedSkillIds": [],
    }
    receipt["sha256"] = compute_receipt_sha256(receipt)

    output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = output_dir / f"{mod}-latest.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    synced_path: str | None = None
    target_archos = archos_receipts_dir
    if target_archos is None:
        env_dir = os.environ.get("ARCHOS_RECEIPTS_DIR", "").strip()
        if env_dir:
            target_archos = Path(env_dir)
    if target_archos is not None and all_passed:
        target_archos.mkdir(parents=True, exist_ok=True)
        dest = target_archos / f"{mod}-latest.json"
        dest.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        synced_path = str(dest)

    return {
        "receipt": receipt,
        "receiptPath": str(receipt_path),
        "syncedArchosPath": synced_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spartan Blind War-Room & Boss-Fight Runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser(
        "start", help="Inject a secret production fault and start MTTR clock"
    )
    p_start.add_argument(
        "--dry-run", action="store_true", help="Do not invoke Docker; arm dry-run incident"
    )
    p_start.add_argument("--seed", type=int, default=None, help="Deterministic RNG seed")
    p_start.add_argument("--fault", type=str, default=None, help="Explicit fault ID override")

    p_verify = sub.add_parser("verify", help="Verify SLA recovery and compute MTTR")
    p_verify.add_argument(
        "--dry-run", action="store_true", help="Simulate SLA pass in dry-run mode"
    )
    p_verify.add_argument("--health-url", type=str, default="http://127.0.0.1:8080/healthz")

    p_boss = sub.add_parser(
        "boss-fight", help="Run module Boss Fight gates and write signed JSON receipt"
    )
    p_boss.add_argument("--module", required=True, help="Module ID (M01..M12)")
    p_boss.add_argument(
        "--dry-run", action="store_true", help="Skip heavy subprocess gates (test mode)"
    )
    p_boss.add_argument("--output-dir", type=Path, default=DEFAULT_RECEIPTS_DIR)
    p_boss.add_argument("--archos-receipts-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command == "start":
        out = start_war_room(dry_run=args.dry_run, seed=args.seed, fault_id=args.fault)
        print(json.dumps(out, indent=2))
        return 0
    if args.command == "verify":
        out = verify_war_room(dry_run=args.dry_run, health_url=args.health_url)
        print(json.dumps(out, indent=2))
        return 0 if out.get("passed") else 1
    if args.command == "boss-fight":
        out = run_boss_fight(
            args.module,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
            archos_receipts_dir=args.archos_receipts_dir,
        )
        print(json.dumps(out, indent=2))
        return 0 if out["receipt"]["passed"] else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
