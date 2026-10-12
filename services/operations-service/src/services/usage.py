"""What operations tells billing about usage (docs/BILLING.md §3).

A customer counts as active for Tenantly's bill when the business serves them or sells
them a plan: a booking checked in or completed, a seat taken in a class, a plan sold. The
event is written to the money outbox in the same transaction as the change behind it, so
usage can't be lost if the change commits, nor invented if it rolls back. Billing counts
each customer once per period whatever the number of events; a class called off sends a
reversal for each seat. No-shows, refunds and cancelled bookings never count.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from .money import enqueue

if TYPE_CHECKING:
    from common.auth import TenantClaims

    from ..models import Booking, Customer

PATH = "/internal/usage"


def _send(claims: TenantClaims, metric: str, subject: str, label: str, source: str, ref: str, delta: int) -> None:
    enqueue(
        claims,
        PATH,
        {
            "metric": metric,
            "subjectKey": subject,
            "label": label[:160],
            "source": source,
            "sourceRef": ref,
            "delta": delta,
            "occurredAt": timezone.now().isoformat(),
        },
    )


def served(claims: TenantClaims, customer: Customer, source: str, ref: str) -> None:
    _send(claims, "active_customers", str(customer.id), customer.name, source, ref, 1)


def unserved(claims: TenantClaims, customer: Customer, ref: str) -> None:
    """The service behind `ref` didn't happen after all (a class called off)."""
    _send(claims, "active_customers", str(customer.id), customer.name, "reversal", ref, -1)


def completed(claims: TenantClaims, booking: Booking) -> None:
    """Bookings handled: shown next to the bill for context, never billed."""
    _send(claims, "bookings", str(booking.id), booking.offering.name, "booking.completed", f"booking:{booking.id}", 1)
