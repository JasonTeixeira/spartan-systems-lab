"""
High-throughput streaming seeder using PostgreSQL COPY FROM STDIN.
Demonstrates Concept #2 (Lazy Generator Streaming) + Concept #19 (Bulk COPY).
Usage:
  uv run python lab-1-core-engine/scripts/seed_events.py --rows 100000
  uv run python lab-1-core-engine/scripts/seed_events.py --rows 10000000
"""
from __future__ import annotations

import argparse
import os
import random
import time
from datetime import UTC, datetime, timedelta

import psycopg

DATABASE_URL = os.getenv(
    "DIRECT_DATABASE_URL",
    "postgresql://spartan:spartanpass@localhost:5432/spartan_lab",
)
EVENT_TYPES = ("api_call", "llm_tokens", "db_query", "storage_gb", "egress_mb")
REGIONS = ("us-east-1", "eu-central-1", "ap-northeast-1", None)


def seed_events(total_rows: int, batch_size: int = 50_000) -> None:
    rng = random.Random(42)
    base_time = datetime.now(UTC) - timedelta(days=30)
    run_tag = int(time.time())
    start = time.monotonic()

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM tenants ORDER BY id")
        tenant_ids = [int(r[0]) for r in cur.fetchall()]
        if not tenant_ids:
            raise RuntimeError("No tenants found. Ensure migrations/001_init.sql ran.")

        copy_sql = (
            "COPY events (tenant_id, idempotency_key, event_type, units, "
            "cost_usd, region, occurred_at) FROM STDIN"
        )
        inserted = 0
        with cur.copy(copy_sql) as copy:
            for i in range(1, total_rows + 1):
                tid = tenant_ids[i % len(tenant_ids)]
                idem = f"seed-{run_tag}-{i}"
                etype = EVENT_TYPES[i % len(EVENT_TYPES)]
                units = rng.randint(1, 500)
                cost = f"{units * 0.00025:.6f}"
                region = REGIONS[i % len(REGIONS)]
                occurred = base_time + timedelta(seconds=rng.randint(0, 30 * 86400))
                copy.write_row((tid, idem, etype, units, cost, region, occurred))
                inserted += 1
                if inserted % batch_size == 0:
                    elapsed = time.monotonic() - start
                    rate = inserted / elapsed
                    print(f"Streamed {inserted:,}/{total_rows:,} rows ({rate:,.0f} rows/s)")
        conn.commit()
        cur.execute("ANALYZE events;")
        conn.commit()

    elapsed = time.monotonic() - start
    rate = total_rows / elapsed
    print(f"Done: inserted {total_rows:,} rows in {elapsed:.2f}s ({rate:,.0f} rows/s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stream synthetic events into Lab 1 Postgres via COPY."
    )
    parser.add_argument("--rows", type=int, default=100_000, help="Number of rows to insert.")
    args = parser.parse_args()
    seed_events(args.rows)
