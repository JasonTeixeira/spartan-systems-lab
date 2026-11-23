# Native database authorization and atomic transfers

From the project root:

```bash
python3 labs/postgres-transfer/demo.py
python3 -m unittest discover -s tests -p 'test_postgres_transfer.py'
```

Requires installed PostgreSQL 14 `postgres`, `initdb`, `pg_ctl`, `psql` and standard-library Python. Nothing is installed automatically. The script creates a new private `/tmp/sage-pg-*` directory, initializes its own cluster and fictional roles, and connects only through that directory's Unix socket. `listen_addresses` is empty; no TCP listener or existing database/service is used. Inherited `PG*` connection variables are removed, `psql -X` skips personal startup files, and no password file is read. Local socket trust assumes the OS account/filesystem are trusted: another process running as the same OS user can impersonate fixture roles. This is not a production login system.

Successful completion stops the owned postmaster, checks it is no longer running, then removes its workspace. Setup failure may retain private diagnostics; uncertain stop status retains the directory and raises rather than deleting active data. A lifecycle regression exposed a closed fixture being re-entered; that exact test cluster was verified, stopped and removed, with a receipt in `proof/postgres-transfer-lifecycle-red-cleanup.json`. The corrected entry guard runs before creating directories. The private socket-directory creation itself can fail before the cleanup try block; that can retain an empty owned directory, not a started server.

Read [the teaching sequence](../../teaching/postgres-transfer/index.md). All balances are fictional integer cents. The negative control intentionally changes a separate owned table to demonstrate that a zero-row update is not automatically an error. The corrected function couples ownership, debit, credit, operation key and saved response in one database transaction. The adapter issues fictional opaque capabilities in memory; the trusted driver, not submitted payload fields, chooses the database login role. `Cluster.query`, `reset`, failure controls and role selection are trusted test APIs, never an exposed SQL endpoint.

The fixed `SECURITY DEFINER` function executes as its privileged owner. It explicitly fences resources using `session_user`, fixes its search path, qualifies tables and restricts execute permission. RLS protects normal app-role reads; it is not the enforcement mechanism inside the owner function. User values are passed using psql's quoted variable interpolation in a fixed SQL statement; arbitrary query text is not accepted by the CLI or adapter.

The demo verifies actual normal PostgreSQL stop/restart and persistent rows. Lost reply is a named exception after confirmed commit, not a real network drop. Policy memory remains in the same Python process, not a recovered identity service. Per-command timeouts, statement/lock timeouts and bounded fixtures do not establish a universal shutdown, filesystem race, OS, latency, power-loss or production availability guarantee. Native checks apply to the observed PostgreSQL 14 edition, not Supabase, Next.js or a deployment. No original sources or learner progress are written.
