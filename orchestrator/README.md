# Spartan Multi-Tenant Cloud Sandbox Orchestrator

Ephemeral per-user Linux/Docker lab control plane powering the **Sage Academy / Spartan War-Room** hosted SaaS experience (`sageideas.dev`).

## Security & Multi-Tenant Isolation

Every provisioned sandbox container enforces CIS/OWASP container hardening:
- `--read-only` root filesystem with bounded `noexec,nosuid` `/tmp` tmpfs
- `--cap-drop=ALL` + `--security-opt=no-new-privileges:true`
- Dedicated per-sandbox `--internal` Docker network (zero east-west tenant traffic)
- Per-tier `--cpus`, `--memory`, `--memory-swap`, and `--pids-limit` quotas
- Constant-time `X-Spartan-Orchestrator-Key` service auth (fail-closed)
- Tenant + user ownership checks on every read/chaos/verify/terminate call (IDOR-proof)
- Short-lived HMAC-SHA256 terminal session tokens bound to `sandbox_id + tenant_id + user_id + exp`
- Deterministic SHA-256 `Lab-Proven` receipt signing compatible with both Supabase and ArchOS

## Local Run

```bash
export SPARTAN_ORCHESTRATOR_API_KEY="dev-local-key-change-me"
export SPARTAN_TERMINAL_SIGNING_SECRET="dev-local-signing-secret-32-chars"
export SPARTAN_SANDBOX_BACKEND="memory" # or "docker" on a Docker host
uv run uvicorn orchestrator.app:app --host 127.0.0.1 --port 8090
```
