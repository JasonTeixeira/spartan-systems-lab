import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from psycopg_pool import ConnectionPool

from app.config import settings
from app.schemas import EventIn, EventOut, TenantSummary

logger = logging.getLogger("spartan.api")
logging.basicConfig(level=settings.log_level, format="%(message)s")

pool: ConnectionPool | None = None

# ------------------------------------------------------------------
# PROMETHEUS RED + BUSINESS/FINOPS METRICS (Scraped at /metrics)
# ------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "spartan_http_requests_total",
    "Total HTTP requests by method, path, and status code",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "spartan_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
EVENTS_INGESTED_TOTAL = Counter(
    "spartan_events_ingested_total",
    "Events ingested by tenant_id, event_type, and outcome",
    ["tenant_id", "event_type", "outcome"],
)
EVENT_COST_USD_TOTAL = Counter(
    "spartan_event_cost_usd_total",
    "Cumulative ingested event cost in USD by tenant_id and event_type",
    ["tenant_id", "event_type"],
)


def log_json(event: str, **fields: object) -> None:
    payload = {"event": event, "ts": time.time(), **fields}
    logger.info(json.dumps(payload, default=str))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global pool
    pool = ConnectionPool(conninfo=settings.database_url, min_size=2, max_size=20, open=False)
    try:
        pool.open(wait=False)
    except Exception as exc:  # pragma: no cover - startup resilience
        log_json("db_pool_init_warning", error=str(exc))
    yield
    if pool is not None:
        pool.close()


app = FastAPI(title="Spartan Lab 1 - Core Engine", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def observability_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    start = time.monotonic()
    response = await call_next(request)
    elapsed_s = time.monotonic() - start
    path = request.url.path

    if path != "/metrics":
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=path,
            status=str(response.status_code),
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            path=path,
        ).observe(elapsed_s)
        log_json(
            "http_request",
            method=request.method,
            path=path,
            status=response.status_code,
            duration_ms=round(elapsed_s * 1000.0, 2),
            request_id=request.headers.get("x-request-id", "local"),
        )
    return response


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    if pool is None:
        raise HTTPException(status_code=503, detail="Database pool not initialized")
    try:
        with pool.connection(timeout=2.0) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB not ready: {exc}") from exc
    return {"status": "ready"}


@app.post("/events", response_model=EventOut, status_code=201)
def ingest_event(payload: EventIn) -> EventOut:
    """
    Idempotent event ingestion using PostgreSQL ON CONFLICT DO NOTHING.
    SPARTAN EXTENSION TODO (Week 1):
      1. Add Redis sliding-window rate limiting per tenant_id.
      2. Add batch ingestion endpoint POST /events/batch using executemany / COPY.
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="Database pool unavailable")

    sql = """
        INSERT INTO events (
            tenant_id, idempotency_key, event_type, units, cost_usd, region, occurred_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
        RETURNING id
    """
    with pool.connection(timeout=3.0) as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            (
                payload.tenant_id,
                payload.idempotency_key,
                payload.event_type,
                payload.units,
                payload.cost_usd,
                payload.region,
                payload.occurred_at,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    if row is None:
        EVENTS_INGESTED_TOTAL.labels(
            tenant_id=str(payload.tenant_id),
            event_type=payload.event_type,
            outcome="duplicate_ignored",
        ).inc()
        return EventOut(
            status="duplicate_ignored",
            event_id=None,
            idempotency_key=payload.idempotency_key,
        )

    EVENTS_INGESTED_TOTAL.labels(
        tenant_id=str(payload.tenant_id),
        event_type=payload.event_type,
        outcome="inserted",
    ).inc()
    EVENT_COST_USD_TOTAL.labels(
        tenant_id=str(payload.tenant_id),
        event_type=payload.event_type,
    ).inc(float(payload.cost_usd))

    return EventOut(
        status="inserted",
        event_id=int(row[0]),
        idempotency_key=payload.idempotency_key,
    )


@app.get("/tenants/{tenant_id}/summary", response_model=TenantSummary)
def tenant_summary(tenant_id: int) -> TenantSummary:
    if pool is None:
        raise HTTPException(status_code=503, detail="Database pool unavailable")

    sql = """
        SELECT
            COUNT(*)::bigint AS event_count,
            COALESCE(SUM(units), 0)::bigint AS total_units,
            COALESCE(SUM(cost_usd), 0)::numeric(14, 6) AS total_cost_usd
        FROM events
        WHERE tenant_id = %s
    """
    with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
        cur.execute(sql, (tenant_id,))
        row = cur.fetchone()

    assert row is not None
    return TenantSummary(
        tenant_id=tenant_id,
        event_count=int(row[0]),
        total_units=int(row[1]),
        total_cost_usd=Decimal(str(row[2])),
    )
