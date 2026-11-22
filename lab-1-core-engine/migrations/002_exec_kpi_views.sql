-- Executive BI & FinOps KPI Views (wired directly to Metabase / Apache Superset)
-- Demonstrates real data pipeline -> SQL modeling layer -> Executive "Money People" Dashboard.

-- 1. Tenant Unit Economics & Budget Cap Risk (CFO / VP View)
CREATE OR REPLACE VIEW v_exec_tenant_unit_economics AS
SELECT
    t.id AS tenant_id,
    t.slug AS tenant_name,
    t.plan,
    t.monthly_cap_usd,
    COUNT(e.id) AS total_events,
    COALESCE(SUM(e.units), 0) AS total_units,
    ROUND(COALESCE(SUM(e.cost_usd), 0), 4) AS total_spend_usd,
    CASE
        WHEN t.monthly_cap_usd > 0
        THEN ROUND((COALESCE(SUM(e.cost_usd), 0) / t.monthly_cap_usd) * 100.0, 2)
        ELSE 0
    END AS cap_utilization_pct,
    CASE
        WHEN COALESCE(SUM(e.units), 0) > 0
        THEN ROUND((COALESCE(SUM(e.cost_usd), 0) / SUM(e.units)) * 1000.0, 6)
        ELSE 0
    END AS cost_per_1k_units_usd,
    CASE
        WHEN t.monthly_cap_usd > 0 AND COALESCE(SUM(e.cost_usd), 0) >= t.monthly_cap_usd THEN 'BREACHED'
        WHEN t.monthly_cap_usd > 0 AND COALESCE(SUM(e.cost_usd), 0) >= (t.monthly_cap_usd * 0.80) THEN 'AT_RISK'
        ELSE 'HEALTHY'
    END AS budget_status
FROM tenants t
LEFT JOIN events e ON e.tenant_id = t.id
GROUP BY t.id, t.slug, t.plan, t.monthly_cap_usd;

-- 2. Daily Spend Trend & Cumulative Running Burn per Tenant (FinOps Time-Series)
CREATE OR REPLACE VIEW v_exec_daily_burn AS
WITH daily AS (
    SELECT
        DATE_TRUNC('day', e.occurred_at)::date AS event_day,
        t.slug AS tenant_name,
        t.plan,
        COUNT(*) AS event_count,
        SUM(e.units) AS total_units,
        SUM(e.cost_usd) AS daily_cost_usd
    FROM events e
    JOIN tenants t ON t.id = e.tenant_id
    GROUP BY 1, 2, 3
)
SELECT
    event_day,
    tenant_name,
    plan,
    event_count,
    total_units,
    ROUND(daily_cost_usd, 4) AS daily_cost_usd,
    ROUND(
        SUM(daily_cost_usd) OVER (PARTITION BY tenant_name ORDER BY event_day),
        4
    ) AS cumulative_spend_usd
FROM daily;

-- 3. Top Cost Drivers by Event Type & Region (Where Are We Bleeding Money?)
CREATE OR REPLACE VIEW v_exec_cost_drivers AS
SELECT
    event_type,
    COALESCE(region, 'unknown') AS region,
    COUNT(*) AS event_count,
    SUM(units) AS total_units,
    ROUND(SUM(cost_usd), 4) AS total_cost_usd,
    ROUND(AVG(cost_usd), 6) AS avg_cost_per_event_usd
FROM events
GROUP BY event_type, COALESCE(region, 'unknown')
ORDER BY total_cost_usd DESC;
