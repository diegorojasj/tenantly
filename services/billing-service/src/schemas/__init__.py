"""Request bodies. Responses are plain dicts shaped for the frontend's types."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from common.schemas import CamelSchema


class ChargeIn(CamelSchema):
    tenant_id: str
    location_id: str
    customer_id: str
    customer_name: str
    booking_id: str | None = None
    description: str
    source: Literal["booking", "dropin", "plan", "fee"]
    amount: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    date: date
    paid: bool = False
    key: str | None = Field(default=None, max_length=64)


class TenantRef(CamelSchema):
    tenant_id: str


class RevenueIn(CamelSchema):
    tenant_id: str
    location_ids: list[str]
    start: date
    end: date


class BalancesIn(CamelSchema):
    tenant_id: str
    customer_ids: list[str] | None = None


class InvoiceIn(CamelSchema):
    customer_id: str
