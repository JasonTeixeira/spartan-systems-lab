import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Request, Response
from psycopg_pool import ConnectionPool

from app.config import settings
from app.schemas import EventIn, EventOut, TenantSummary

logger = logging.getLogger("spartan.api")
logging.basicConfig(level=settings.log_level, format="%(message)s")

pool: ConnectionPool | None = None


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
async def structured_logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000.0, 2)
    log_json(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        request_id=request.headers.get("x-request-id", "local"),
    )
    return response


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
        return EventOut(
            status="duplicate_ignored",
            event_id=None,
            idempotency_key=payload.idempotency_key,
        )
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
