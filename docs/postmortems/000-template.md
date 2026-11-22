# Post-Mortem: [Incident / Drill Title]

- **Date:** YYYY-MM-DD
- **Lab / Chaos Scenario:** e.g., Lab 1 `lock-storm`
- **MTTD (Time to Detect):** X min Y sec
- **MTTR (Time to Mitigate):** X min Y sec

## 1. User-Visible Symptoms
What broke? (HTTP status codes, p99 spike, timeouts, error rate)

## 2. Exact Commands That Isolated Root Cause
```bash
# Paste the exact terminal commands (ss, strace, tcpdump, EXPLAIN, pg_stat_activity) and key output lines
```

## 3. Root Cause Analysis
Why did the failure happen at the OS / network / database / application level?

## 4. Immediate Mitigation vs. Permanent Fix
- **Immediate mitigation (stop the bleeding):**
- **Permanent engineering fix (prevent recurrence):**

## 5. Regression Test / Alert Added
Link to the test, migration, timeout, or Prometheus alert added to prevent this class of outage forever.
