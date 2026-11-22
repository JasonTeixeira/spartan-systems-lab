from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    tenant_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=4, max_length=128)
    event_type: str = Field(min_length=1, max_length=64)
    units: int = Field(gt=0)
    cost_usd: Decimal = Field(ge=Decimal("0"))
    region: str | None = Field(default=None, max_length=32)
    occurred_at: datetime


class EventOut(BaseModel):
    status: str
    event_id: int | None = None
    idempotency_key: str


class TenantSummary(BaseModel):
    tenant_id: int
    event_count: int
    total_units: int
    total_cost_usd: Decimal
