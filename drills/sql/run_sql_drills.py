"""
Spartan 15-Challenge Executable PostgreSQL 16 Drill Runner (`make drill-sql`).

Supports:
  - `--list` (zero-Docker catalog view & validation)
  - `--run`  (executes all 15 reference verification queries against Lab 1 Postgres via psql)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SqlDrill:
    id: str
    title: str
    pattern: str
    prompt: str
    verify_sql: str


SQL_DRILLS: tuple[SqlDrill, ...] = (
    SqlDrill(
        id="sql-01",
        title="Latest Event Per Tenant (Dedup)",
        pattern="ROW_NUMBER() OVER (PARTITION BY ...)",
        prompt="Return the single most recent event per tenant_id ordered by occurred_at DESC, id DESC.",
        verify_sql=(
            "SELECT count(*) FROM ("
            "SELECT tenant_id, ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY occurred_at DESC, id DESC) AS rn "
            "FROM events) t WHERE rn = 1;"
        ),
    ),
    SqlDrill(
        id="sql-02",
        title="The NOT IN NULL 3-Valued Logic Trap",
        pattern="NOT EXISTS anti-join",
        prompt="Find tenants whose slug does not appear in events.region even when region contains NULLs.",
        verify_sql=(
            "SELECT count(*) FROM tenants t "
            "WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.region = t.slug);"
        ),
    ),
    SqlDrill(
        id="sql-03",
        title="Cumulative Daily Spend & Day-over-Day Delta",
        pattern="SUM() OVER + LAG()",
        prompt="Compute daily total cost_usd per tenant with cumulative running total and previous-day LAG().",
        verify_sql=(
            "WITH daily AS ("
            "SELECT tenant_id, date_trunc('day', occurred_at) AS day, sum(cost_usd) AS spend "
            "FROM events GROUP BY 1, 2) "
            "SELECT count(*) FROM ("
            "SELECT tenant_id, day, spend, "
            "sum(spend) OVER (PARTITION BY tenant_id ORDER BY day) AS running_spend, "
            "spend - lag(spend) OVER (PARTITION BY tenant_id ORDER BY day) AS delta "
            "FROM daily) q;"
        ),
    ),
    SqlDrill(
        id="sql-04",
        title="EXPLAIN (ANALYZE, BUFFERS) Plan Inspection",
        pattern="Composite B-Tree Leftmost Prefix",
        prompt="Inspect plan node and shared buffers for tenant_id=1 ORDER BY occurred_at DESC LIMIT 25.",
        verify_sql=(
            "EXPLAIN (FORMAT JSON) SELECT id, event_type, cost_usd, occurred_at "
            "FROM events WHERE tenant_id = 1 ORDER BY occurred_at DESC LIMIT 25;"
        ),
    ),
    SqlDrill(
        id="sql-05",
        title="Gaps & Islands Active Streak Detection",
        pattern="ROW_NUMBER() difference grouping",
        prompt="Group consecutive active calendar days per tenant into contiguous island ranges.",
        verify_sql=(
            "WITH days AS (SELECT DISTINCT tenant_id, occurred_at::date AS d FROM events), "
            "grp AS (SELECT tenant_id, d, d - (ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY d))::int AS island FROM days) "
            "SELECT count(*) FROM (SELECT tenant_id, min(d), max(d), count(*) FROM grp GROUP BY tenant_id, island) s;"
        ),
    ),
    SqlDrill(
        id="sql-06",
        title="Queue Worker Claim Without Contention",
        pattern="FOR UPDATE SKIP LOCKED",
        prompt="Safely claim 5 pending rows inside a transaction without blocking concurrent workers.",
        verify_sql=(
            "BEGIN; "
            "SELECT id FROM events ORDER BY id LIMIT 5 FOR UPDATE SKIP LOCKED; "
            "ROLLBACK;"
        ),
    ),
    SqlDrill(
        id="sql-07",
        title="Top-3 Most Expensive Events Per Tenant",
        pattern="LATERAL JOIN",
        prompt="Fetch the top 3 highest-cost events for every tenant using a correlated LATERAL join.",
        verify_sql=(
            "SELECT count(*) FROM tenants t "
            "CROSS JOIN LATERAL ("
            "SELECT e.id, e.cost_usd FROM events e WHERE e.tenant_id = t.id ORDER BY e.cost_usd DESC LIMIT 3"
            ") top_e;"
        ),
    ),
    SqlDrill(
        id="sql-08",
        title="Percentile Latency / Cost SLA (p95 & p99)",
        pattern="PERCENTILE_CONT WITHIN GROUP",
        prompt="Compute p50, p95, and p99 cost_usd across all events using ordered-set aggregates.",
        verify_sql=(
            "SELECT percentile_cont(0.50) WITHIN GROUP (ORDER BY cost_usd) AS p50, "
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY cost_usd) AS p95, "
            "percentile_cont(0.99) WITHIN GROUP (ORDER BY cost_usd) AS p99 FROM events;"
        ),
    ),
    SqlDrill(
        id="sql-09",
        title="Recursive CTE Hierarchy / DAG Traversal",
        pattern="WITH RECURSIVE",
        prompt="Generate a 14-day calendar spine with WITH RECURSIVE and left-join daily event counts.",
        verify_sql=(
            "WITH RECURSIVE spine(day) AS ("
            "SELECT current_date - 13 UNION ALL SELECT day + 1 FROM spine WHERE day < current_date) "
            "SELECT count(*) FROM spine;"
        ),
    ),
    SqlDrill(
        id="sql-10",
        title="Conditional Aggregation Funnel Pivot",
        pattern="COUNT(*) FILTER (WHERE ...)",
        prompt="Pivot event types into side-by-side counts per tenant using SQL-standard FILTER clauses.",
        verify_sql=(
            "SELECT tenant_id, count(*) AS total, "
            "count(*) FILTER (WHERE cost_usd > 0) AS billable "
            "FROM events GROUP BY tenant_id LIMIT 10;"
        ),
    ),
    SqlDrill(
        id="sql-11",
        title="Idempotent Upsert Verification (Dry-Run Rollback)",
        pattern="INSERT ... ON CONFLICT DO UPDATE",
        prompt="Verify idempotent tenant upsert inside a rolled-back transaction.",
        verify_sql=(
            "BEGIN; "
            "INSERT INTO tenants (slug, name, monthly_budget_usd) VALUES ('drill-canary', 'Drill Canary', 500) "
            "ON CONFLICT (slug) DO UPDATE SET monthly_budget_usd = EXCLUDED.monthly_budget_usd; "
            "ROLLBACK;"
        ),
    ),
    SqlDrill(
        id="sql-12",
        title="7-Day Rolling Window Average Spend",
        pattern="RANGE BETWEEN '6 days' PRECEDING",
        prompt="Compute a 7-day rolling spend average per tenant handling missing calendar days.",
        verify_sql=(
            "WITH daily AS (SELECT tenant_id, occurred_at::date AS d, sum(cost_usd) AS spend FROM events GROUP BY 1, 2) "
            "SELECT count(*) FROM ("
            "SELECT tenant_id, d, avg(spend) OVER (PARTITION BY tenant_id ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) "
            "FROM daily) r;"
        ),
    ),
    SqlDrill(
        id="sql-13",
        title="MVCC Dead Tuples & Autovacuum Health Audit",
        pattern="pg_stat_user_tables",
        prompt="Inspect live vs dead tuple ratios and last_autovacuum across all user tables.",
        verify_sql=(
            "SELECT relname, n_live_tup, n_dead_tup, last_autovacuum "
            "FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;"
        ),
    ),
    SqlDrill(
        id="sql-14",
        title="Active Lock Contention & Wait-Event X-Ray",
        pattern="pg_stat_activity + pg_locks",
        prompt="Verify zero ungranted locks and inspect wait_event_type distribution.",
        verify_sql=(
            "SELECT count(*) AS ungranted_locks FROM pg_locks WHERE NOT granted;"
        ),
    ),
    SqlDrill(
        id="sql-15",
        title="Write-Skew Serializable Isolation Check",
        pattern="BEGIN ISOLATION LEVEL SERIALIZABLE",
        prompt="Verify SERIALIZABLE transaction isolation mode works cleanly on Lab 1 Postgres.",
        verify_sql=(
            "BEGIN ISOLATION LEVEL SERIALIZABLE; "
            "SELECT count(*) FROM tenants; "
            "COMMIT;"
        ),
    ),
)


def list_drills() -> list[dict[str, str]]:
    return [asdict(d) for d in SQL_DRILLS]


def run_drills_live() -> int:
    passed = 0
    for drill in SQL_DRILLS:
        proc = subprocess.run(
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
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                drill.verify_sql,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            passed += 1
            print(f"[PASS] {drill.id} · {drill.title} ({drill.pattern})")
        else:
            print(f"[FAIL] {drill.id} · {drill.title}: {proc.stderr.strip()}")
    print(f"\nSQL Drills Passed: {passed}/{len(SQL_DRILLS)}")
    return 0 if passed == len(SQL_DRILLS) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spartan 15-Challenge PostgreSQL Drill Runner")
    parser.add_argument("--list", action="store_true", help="Print all 15 SQL drills as JSON")
    parser.add_argument("--run", action="store_true", help="Run all 15 SQL verification queries against Lab 1 Postgres")
    args = parser.parse_args(argv)
    if args.run:
        return run_drills_live()
    print(json.dumps({"count": len(SQL_DRILLS), "drills": list_drills()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
