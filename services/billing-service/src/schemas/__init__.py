"""Request bodies. Responses are plain dicts shaped for the frontend's types."""

from __future__ import annotations

import uuid
from datetime import date, datetime
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


class SettledIn(CamelSchema):
    tenant_id: str
    booking_ids: list[str]


class InvoiceIn(CamelSchema):
    customer_id: str


# ------------------------------------------------------------ Tenantly plan --


class UsageIn(CamelSchema):
    """One usage event from operations' outbox; `key` is the outbox id, unique per tenant."""

    tenant_id: str
    metric: Literal["active_customers", "bookings"]
    subject_key: str = Field(max_length=64)
    label: str = Field(default="", max_length=160)
    source: str = Field(max_length=30)
    source_ref: str = Field(max_length=100)
    delta: Literal[1, -1] = 1
    occurred_at: datetime
    key: str = Field(max_length=64)


class PlanChangeIn(CamelSchema):
    """The business picks a public plan by code; the price is always billing's, never the client's."""

    plan: Literal["starter", "growth", "enterprise"]
    revision: int


class PlanSettingsIn(CamelSchema):
    spend_cap: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    alert_thresholds: list[int] = Field(default_factory=lambda: [80, 100], max_length=4)


class CardIn(CamelSchema):
    return_url: str = Field(max_length=500)


class CustomTermsIn(CamelSchema):
    """A Custom plan as agreed with the business; a limit left out means none."""

    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    customer_limit: int | None = Field(default=None, ge=1)
    overage_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class ActorIn(CamelSchema):
    """The Tenantly admin acting from the console; audit entries and history name them."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)


class PlanAssignIn(CamelSchema):
    """Set by Tenantly staff (identity's `manage.py set_plan` or admin console), never by the business."""

    plan: Literal["starter", "growth", "enterprise", "custom"]
    terms: CustomTermsIn | None = None
    reason: str = Field(default="", max_length=200)
    # Left out by the CLI: the change is then signed "Tenantly".
    actor: ActorIn | None = None


# ------------------------------------------------------- admin console --


class SummariesIn(CamelSchema):
    tenant_ids: list[uuid.UUID] = Field(max_length=500)


class GrantIn(CamelSchema):
    """An exception Tenantly authorises (services/grants.py): bounded in time, with a reason."""

    kind: Literal["extra_allowance", "discount_pct", "waive_overage", "extend_grace", "dispute"]
    metric: Literal["active_customers", ""] = ""
    value: Decimal = Field(default=Decimal(0), ge=0, max_digits=10, decimal_places=2)
    days: int = Field(default=31, ge=1, le=366)
    reason: str = Field(min_length=1, max_length=200)
    actor: ActorIn | None = None


class InvoicePaidIn(CamelSchema):
    reference: str = Field(min_length=1, max_length=120)
    actor: ActorIn | None = None


class RepriceIn(CamelSchema):
    """A public plan's new price list; included / overage / cap left out mean none."""

    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    included: int | None = Field(default=None, ge=1)
    overage_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    cap: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    reason: str = Field(min_length=1, max_length=200)
    actor: ActorIn | None = None


class PolicyIn(CamelSchema):
    """The billing policy as it should read from now on (services/policy.py validates it)."""

    limit_after_days: int
    restrict_after_days: int
    cancel_after_days: int
    payment_terms_days: int
    small_balance: Decimal = Field(max_digits=10, decimal_places=2)
    extension_days: int
    extension_every_days: int
    retention_days: int
    usage_grace_hours: int
    spend_cap_multiple: Decimal = Field(max_digits=5, decimal_places=2)
    alert_thresholds: list[int] = Field(max_length=4)
    reason: str = Field(min_length=1, max_length=200)
    actor: ActorIn | None = None
