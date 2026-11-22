# Spartan Cold Drill - Day 01: Production SQL (PostgreSQL 16)

> **Setup:** Boot Lab 1 (`make up`), seed 100k+ rows (`make seed ROWS=250000`), then open `make psql`.
> Write every query yourself first using your PDF field manual (Parts 1, 2, 7 & 10).

---

### Drill 1: Deduplicate / Latest Event Per Tenant (Task 10 - Window Functions)
Write a single query returning the **most recent event** (`occurred_at DESC`, tie-break `id DESC`) for each `tenant_id` using `ROW_NUMBER() OVER (PARTITION BY ...)`.

### Drill 2: The `NOT IN` NULL Trap (Concept 122 & Senior Trap #5)
Notice `events.region` contains `NULL` values.
1. Run a query trying to find tenants whose `slug` is `NOT IN (SELECT region FROM events)` — observe why PostgreSQL returns **0 rows**.
2. Rewrite it safely with `NOT EXISTS` and explain 3-valued logic (`TRUE`, `FALSE`, `UNKNOWN`).

### Drill 3: Running Daily Spend & Period-over-Period Delta (Concept 17)
Compute daily total `cost_usd` per `tenant_id`, plus:
- A cumulative running total (`SUM(...) OVER (PARTITION BY tenant_id ORDER BY day)`)
- Previous day's spend using `LAG(...)`

### Drill 4: `EXPLAIN (ANALYZE, BUFFERS)` + Composite Index Speedup (Task 11 & Law #4)
1. Run:
   ```sql
   EXPLAIN (ANALYZE, BUFFERS)
   SELECT id, event_type, cost_usd, occurred_at
   FROM events
   WHERE tenant_id = 1
   ORDER BY occurred_at DESC
   LIMIT 25;
   ```
2. Record the **Execution Time**, **Plan Node** (`Seq Scan` vs `Index Scan`), and **Shared Hit/Read Buffers**.
3. Create the optimal **composite B-Tree index** following the Leftmost Prefix Rule (`CREATE INDEX CONCURRENTLY ...`).
4. Re-run `EXPLAIN (ANALYZE, BUFFERS)` and record the speedup in `docs/adr/002-events-composite-index.md`.

### Drill 5: Safe Blast-Radius Verification (Career Habit #3)
Before ever updating rows in production:
1. Run `SELECT COUNT(*)` with your exact `WHERE` predicate.
2. Wrap a test `UPDATE` inside `BEGIN; ...; SELECT ...; ROLLBACK;` to prove zero unintended rows were touched.
