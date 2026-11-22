-- Spartan Read-Only PostgreSQL X-Ray Diagnostics (Safe for Production Inspection)
-- Usage inside Lab 1: docker compose -f lab-1-core-engine/docker-compose.yml exec -T postgres psql -U spartan -d spartan_lab < tools/sql-diagnostics/pg_xray.sql

\echo '=== 1. CONNECTION & STATE BREAKDOWN ==='
SELECT state, wait_event_type, wait_event, COUNT(*) AS conn_count
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY 1, 2, 3
ORDER BY conn_count DESC;

\echo '=== 2. LONG-RUNNING & IDLE-IN-TRANSACTION SESSIONS (>5s) ==='
SELECT pid, usename, state, wait_event_type, wait_event,
       age(clock_timestamp(), query_start) AS query_age,
       age(clock_timestamp(), xact_start) AS xact_age,
       left(query, 100) AS query_snippet
FROM pg_stat_activity
WHERE datname = current_database()
  AND state <> 'idle'
  AND pid <> pg_backend_pid()
ORDER BY xact_age DESC NULLS LAST
LIMIT 15;

\echo '=== 3. BLOCKED QUERIES & LOCK CONTENTION ==='
SELECT blocked.pid AS blocked_pid,
       blocking.pid AS blocking_pid,
       age(clock_timestamp(), blocked.query_start) AS blocked_for,
       left(blocked.query, 80) AS blocked_query,
       left(blocking.query, 80) AS blocking_query
FROM pg_stat_activity blocked
JOIN pg_stat_activity blocking
  ON blocking.pid = ANY(pg_blocking_pids(blocked.pid));

\echo '=== 4. BUFFER CACHE HIT RATIO (TARGET > 99% FOR OLTP) ==='
SELECT
    SUM(heap_blks_read) AS heap_read,
    SUM(heap_blks_hit) AS heap_hit,
    ROUND(
        CASE WHEN SUM(heap_blks_hit) + SUM(heap_blks_read) = 0 THEN 100.0
             ELSE (SUM(heap_blks_hit)::numeric / (SUM(heap_blks_hit) + SUM(heap_blks_read))) * 100.0
        END, 2
    ) AS cache_hit_ratio_pct
FROM pg_statio_user_tables;

\echo '=== 5. SEQUENTIAL SCANS & DEAD TUPLE BLOAT (MISSING INDEXES & VACUUM HEALTH) ==='
SELECT relname AS table_name,
       seq_scan,
       idx_scan,
       n_live_tup,
       n_dead_tup,
       ROUND(CASE WHEN n_live_tup > 0 THEN (n_dead_tup::numeric / n_live_tup) * 100 ELSE 0 END, 2) AS dead_pct,
       last_autovacuum,
       last_autoanalyze
FROM pg_stat_user_tables
ORDER BY seq_scan DESC, n_dead_tup DESC
LIMIT 15;

\echo '=== 6. TRANSACTION ID (XID) WRAPAROUND SAFETY CHECK ==='
SELECT datname,
       age(datfrozenxid) AS xid_age,
       ROUND((age(datfrozenxid)::numeric / 2000000000.0) * 100.0, 2) AS pct_to_wraparound
FROM pg_database
ORDER BY xid_age DESC;

\echo '=== 7. TOP 10 SLOWEST QUERIES BY TOTAL TIME (pg_stat_statements) ==='
SELECT calls,
       ROUND(total_exec_time::numeric, 2) AS total_ms,
       ROUND(mean_exec_time::numeric, 2) AS mean_ms,
       rows,
       left(query, 100) AS query_snippet
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
