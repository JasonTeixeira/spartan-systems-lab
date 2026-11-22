from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import app
from app.schemas import EventIn


def test_healthz_endpoint() -> None:
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_event_in_validates_financial_precision_and_bounds() -> None:
    evt = EventIn(
        tenant_id=1,
        idempotency_key="evt-0001",
        event_type="api_call",
        units=25,
        cost_usd=Decimal("0.012500"),
        region="us-east-1",
        occurred_at=datetime.now(UTC),
    )
    assert evt.cost_usd == Decimal("0.012500")

    with pytest.raises(ValidationError):
        EventIn(
            tenant_id=0,
            idempotency_key="bad",
            event_type="api_call",
            units=-5,
            cost_usd=Decimal("-1.0"),
            occurred_at=datetime.now(UTC),
        )


def test_settings_defaults() -> None:
    cfg = Settings()
    assert cfg.rate_limit_per_minute > 0
    assert cfg.database_url.startswith("postgresql://")
