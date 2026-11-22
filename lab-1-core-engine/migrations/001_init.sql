-- Lab 1 Initial Schema: Normalized 3NF + Financial Precision + Constraints
-- Deliberately omits a composite index on events(tenant_id, occurred_at DESC)
-- so you experience a real Seq Scan in EXPLAIN (ANALYZE, BUFFERS) during Day 1 SQL drills.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE IF NOT EXISTS tenants (
    id              BIGSERIAL PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    plan            TEXT NOT NULL CHECK (plan IN ('free', 'pro', 'enterprise')),
    monthly_cap_usd NUMERIC(14, 4) NOT NULL CHECK (monthly_cap_usd >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    idempotency_key  TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    units            INTEGER NOT NULL CHECK (units > 0),
    cost_usd         NUMERIC(14, 6) NOT NULL CHECK (cost_usd >= 0),
    region           TEXT,
    occurred_at      TIMESTAMPTZ NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_events_tenant_idem UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS etl_watermarks (
    pipeline_name   TEXT PRIMARY KEY,
    last_occurred   TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO tenants (slug, plan, monthly_cap_usd)
VALUES
    ('acme-corp', 'enterprise', 5000.0000),
    ('beta-labs', 'pro', 500.0000),
    ('gamma-io', 'free', 25.0000)
ON CONFLICT (slug) DO NOTHING;
