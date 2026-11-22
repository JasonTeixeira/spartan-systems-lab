# Spartan Cold Drill - Day 01: Linux SRE Triage & Network Forensics

> **Setup:** Boot Lab 1 (`make up`) and enter your real Linux toolbox container: `make sre-shell`.

---

### Drill 1: Verify Real Network Segmentation (Public vs. Private Subnets)
From inside `sre-toolbox` (and test from inside `spartan-nginx` too):
```bash
# 1. Inspect interfaces & private subnet CIDRs
ip -br addr
ip route

# 2. Verify DNS resolution inside Docker's embedded resolver
dig nginx +short
dig api +short
dig postgres +short

# 3. Verify nginx CANNOT reach postgres directly (private_data_net isolation!)
# Run from your Mac host:
docker exec spartan-nginx sh -c "nc -zv -w 2 postgres 5432 || echo 'BLOCKED AS EXPECTED'"
```

### Drill 2: The 60-Second Linux Triage Pass
Inside `sre-toolbox`, run and interpret every line:
```bash
uptime
vmstat 1 3
mpstat -P ALL 1 2
iostat -xz 1 2
free -m
ss -s
```

### Drill 3: Live Wire Inspection (`curl -v` + `tcpdump`)
1. Watch live HTTP headers & Nginx reverse-proxy request timing:
   ```bash
   curl -v http://nginx/healthz
   ```
2. Capture raw TCP handshakes (`SYN`, `SYN-ACK`, `ACK`) between `sre-toolbox` and `nginx`:
   ```bash
   tcpdump -nn -i any -c 20 'host nginx and port 80'
   ```

### Drill 4: Live Outage War Room (`lock-storm` & `net-latency`)
1. In Terminal 1: `make chaos SCENARIO=lock-storm`
2. In Terminal 2: hit `curl http://localhost:8080/tenants/1/summary` (watch it hang!), then open `make psql` and run:
   ```sql
   SELECT pid, state, wait_event_type, wait_event,
          age(clock_timestamp(), query_start) AS duration, left(query, 80)
   FROM pg_stat_activity
   WHERE datname = 'spartan_lab'
   ORDER BY duration DESC;
   ```
3. Next, inject artificial WAN latency: `make chaos SCENARIO=net-latency`, measure with `curl` from `sre-toolbox`, then clean up with `make chaos SCENARIO=clear-latency`.
4. Log your findings using `docs/postmortems/000-template.md`.
