"""Money lives in the billing service; this is operations' only door to it.

Writes (charges, refunds) go through the `MoneyEvent` outbox so they commit or
roll back with the booking change that caused them; reads call billing directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

from common.errors import ApiError
from common.internal import call
from common.money import wire

from ..models import MoneyEvent

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from common.auth import TenantClaims

    from ..models import Customer

log = logging.getLogger(__name__)

DISPATCH_BATCH = 200


def _enqueue(claims: TenantClaims, path: str, body: dict[str, Any]) -> None:
    MoneyEvent.objects.create(tenant_id=claims.tenant_id, path=path, body={"tenantId": claims.tenant_id, **body})
    transaction.on_commit(dispatch, robust=True)


def raise_charge(  # noqa: PLR0913 - mirrors the charge's own fields
    claims: TenantClaims,
    customer: Customer,
    *,
    location_id: str,
    description: str,
    source: str,
    amount: Decimal,
    on: date,
    paid: bool,
    booking_id: str | None = None,
) -> None:
    """Filed under the location that did the work, not the customer's home location."""
    _enqueue(
        claims,
        "/internal/charges",
        {
            "locationId": location_id,
            "customerId": str(customer.id),
            "customerName": customer.name,
            "bookingId": booking_id,
            "description": description,
            "source": source,
            "amount": wire(amount),
            "currency": claims.currency,
            "date": on.isoformat(),
            "paid": paid,
        },
    )


def refund_booking(claims: TenantClaims, booking_id: str) -> None:
    _enqueue(claims, f"/internal/bookings/{booking_id}/refund", {})


def dispatch(limit: int = DISPATCH_BATCH) -> int:
    """Send pending events oldest first; returns how many were sent.

    Order matters within a tenant (a cancellation's refund must land before its
    late-cancel fee), so the first failure for a tenant holds back the rest of
    that tenant's events until the next run. Other tenants carry on.
    """
    sent = 0
    held: set[Any] = set()
    for _ in range(limit):
        with transaction.atomic():
            event = (
                MoneyEvent.objects.select_for_update()
                .filter(sent_at__isnull=True)
                .exclude(tenant_id__in=held)
                .order_by("id")
                .first()
            )
            if not event:
                break
            try:
                call("billing", "POST", event.path, json={**event.body, "key": f"ops-{event.id}"})
            except (ApiError, RuntimeError) as exc:
                log.warning("money event %s failed (attempt %s): %s", event.id, event.attempts + 1, exc)
                event.attempts += 1
                event.error = str(exc)[:300]
                event.save(update_fields=["attempts", "error"])
                held.add(event.tenant_id)
                continue
            event.sent_at = timezone.now()
            event.error = ""
            event.save(update_fields=["sent_at", "error"])
            sent += 1
    return sent


def balances(claims: TenantClaims, customer_ids: list[str] | None = None) -> dict[str, dict[str, str]]:
    """Per customer: `spend` (paid) and `balance` (owed), as decimal strings."""
    return call(
        "billing", "POST", "/internal/balances", json={"tenantId": claims.tenant_id, "customerIds": customer_ids}
    )


def customer_charges(claims: TenantClaims, customer_id: str) -> list[dict[str, Any]]:
    return call("billing", "GET", f"/internal/customers/{customer_id}/charges", params={"tenant_id": claims.tenant_id})


def revenue(claims: TenantClaims, location_ids: set[str], start: date, end: date) -> dict[str, Any]:
    """`{"byDay": {date: amount}, "byLocation": {id: amount}}` for not-refunded charges (decimal strings)."""
    return call(
        "billing",
        "POST",
        "/internal/revenue",
        json={
            "tenantId": claims.tenant_id,
            "locationIds": sorted(location_ids),
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
    )
