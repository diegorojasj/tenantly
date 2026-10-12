"""Charges: raising, collecting, refunding, and reading them per scope."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.internal import audit
from common.money import ZERO, label, wire

from ..models import Charge
from . import invoices

if TYPE_CHECKING:
    from common.auth import TenantClaims

    from ..schemas import ChargeIn

WORK = ("bookings.manage", "analytics.view")
MONEY = ("payments.collect", "analytics.view")
LIST_LIMIT = 300


def today() -> date:
    return timezone.now().date()


def status_of(charge: Charge, on: date) -> str:
    overdue_before = on - timedelta(days=settings.OVERDUE_AFTER_DAYS)
    if charge.status == Charge.Status.DUE and charge.date < overdue_before:
        return "overdue"
    return charge.status


def charge_dict(charge: Charge, on: date) -> dict[str, Any]:
    return {
        "id": str(charge.id),
        "customerId": str(charge.customer_id),
        "customerName": charge.customer_name,
        "locationId": str(charge.location_id),
        "description": charge.description,
        "source": "plan" if charge.source == Charge.Source.PLAN else "booking",
        "amount": wire(charge.amount),
        "currency": charge.currency,
        "date": charge.date.isoformat(),
        "status": status_of(charge, on),
        "invoiceId": str(charge.invoice_id) if charge.invoice_id else None,
        "bookingId": str(charge.booking_id) if charge.booking_id else None,
    }


def _money(value: Decimal | None) -> str:
    return wire(value or ZERO)


# ------------------------------------------------------------- reading --


def payments(claims: TenantClaims, scope: str | None) -> dict[str, Any]:
    claims.demand_any(MONEY)
    now = today()
    month_ago = now - timedelta(days=30)
    rows = Charge.objects.filter(tenant_id=claims.tenant_id, location_id__in=claims.locations(scope))
    overdue_before = now - timedelta(days=settings.OVERDUE_AFTER_DAYS)
    due = rows.filter(status=Charge.Status.DUE)
    summary = {
        "collected30": _money(
            rows.filter(status=Charge.Status.PAID, paid_on__gte=month_ago).aggregate(s=Sum("amount"))["s"]
        ),
        "due": _money(due.filter(date__gte=overdue_before).aggregate(s=Sum("amount"))["s"]),
        "overdue": _money(due.filter(date__lt=overdue_before).aggregate(s=Sum("amount"))["s"]),
        "refunded30": _money(
            rows.filter(status=Charge.Status.REFUNDED, date__gte=month_ago).aggregate(s=Sum("amount"))["s"]
        ),
    }
    # Open charges first, oldest debt on top; then the last 30 days of history.
    open_rows = list(due.order_by("date")[:LIST_LIMIT])
    settled = list(
        rows.exclude(status=Charge.Status.DUE).filter(date__gte=month_ago).order_by("-paid_on", "-date")[:LIST_LIMIT]
    )
    return {
        "canCollect": claims.can("payments.collect"),
        "currency": claims.currency,
        "summary": summary,
        "charges": [charge_dict(c, now) for c in [*open_rows, *settled]],
    }


def for_booking(claims: TenantClaims, booking_id: str) -> dict[str, Any]:
    """What one booking raised (its price, a drop-in seat, fees), for the booking panel.

    Staff who run bookings see it so they can tell the customer what's owed; only
    `payments.collect` acts on it. Roles that see neither get an empty answer, not an error.
    """
    now = today()
    if not any(claims.can(p) for p in (*WORK, *MONEY)):
        return {"canSee": False, "canCollect": False, "charges": []}
    rows = Charge.objects.filter(tenant_id=claims.tenant_id, booking_id=booking_id).order_by("created_at")
    return {
        "canSee": True,
        "canCollect": claims.can("payments.collect"),
        "charges": [charge_dict(c, now) for c in rows if claims.reaches(str(c.location_id))],
    }


def settled(tenant_id: str, booking_ids: list[str]) -> list[str]:
    """Of these bookings, the ones whose charges were all paid after the fact (collected or invoiced)."""
    rows = Charge.objects.filter(tenant_id=tenant_id, booking_id__in=booking_ids).exclude(status=Charge.Status.REFUNDED)
    paid: set[str] = set()
    owed: set[str] = set()
    for booking_id, status in rows.values_list("booking_id", "status"):
        (owed if status == Charge.Status.DUE else paid).add(str(booking_id))
    return sorted(paid - owed)


def revenue(claims: TenantClaims, scope: str | None, start: date, end: date) -> dict[str, str]:
    """Revenue raised per day (anything not refunded), by charge date."""
    claims.demand_any(WORK)
    rows = (
        Charge.objects.filter(
            tenant_id=claims.tenant_id,
            location_id__in=claims.locations(scope),
            date__gte=start,
            date__lte=end,
        )
        .exclude(status=Charge.Status.REFUNDED)
        .values("date")
        .annotate(total=Sum("amount"))
    )
    return {r["date"].isoformat(): wire(r["total"]) for r in rows}


def revenue_split(tenant_id: str, location_ids: list[str], start: date, end: date) -> dict[str, dict[str, str]]:
    """Revenue (anything not refunded) per day and per location, for insights and Today."""
    rows = (
        Charge.objects.filter(tenant_id=tenant_id, location_id__in=location_ids, date__gte=start, date__lte=end)
        .exclude(status=Charge.Status.REFUNDED)
        .values("date", "location_id")
        .annotate(total=Sum("amount"))
    )
    by_day: dict[str, Decimal] = defaultdict(Decimal)
    by_location: dict[str, Decimal] = defaultdict(Decimal)
    for r in rows:
        by_day[r["date"].isoformat()] += r["total"]
        by_location[str(r["location_id"])] += r["total"]
    return {
        "byDay": {k: wire(v) for k, v in by_day.items()},
        "byLocation": {k: wire(v) for k, v in by_location.items()},
    }


# ------------------------------------------------------------- writing --


@transaction.atomic
def settle(claims: TenantClaims, charge_id: str, action: str) -> Charge:
    claims.demand("payments.collect")
    charge = Charge.objects.select_for_update(of=("self",)).filter(tenant_id=claims.tenant_id, id=charge_id).first()
    if not charge or not claims.reaches(str(charge.location_id)):
        msg = _("That charge is outside your scope")
        raise NotFoundError(msg)
    if action == "collect":
        if charge.status != Charge.Status.DUE:
            msg = _("Only open charges can be collected")
            raise InvalidError(msg)
        if charge.invoice_id:
            msg = _("That charge is on an open invoice: collect the invoice instead")
            raise InvalidError(msg)
        charge.status = Charge.Status.PAID
        charge.paid_on = today()
    else:
        if charge.status != Charge.Status.PAID:
            msg = _("Only paid charges can be refunded")
            raise InvalidError(msg)
        charge.status = Charge.Status.REFUNDED
    charge.save(update_fields=["status", "paid_on"])
    audit(
        claims,
        "charge.collected" if action == "collect" else "charge.refunded",
        "billing",
        f"{charge.customer_name} · {label(charge.amount, charge.currency)} · {charge.description}",
        str(charge.location_id),
    )
    return charge


def create(body: ChargeIn) -> Charge:
    """Idempotent on `key`: replaying the same request returns the charge it already raised."""
    if body.key:
        existing = Charge.objects.filter(tenant_id=body.tenant_id, key=body.key).first()
        if existing:
            return existing
    return Charge.objects.create(
        key=body.key,
        tenant_id=body.tenant_id,
        location_id=body.location_id,
        customer_id=body.customer_id,
        customer_name=body.customer_name,
        booking_id=body.booking_id,
        description=body.description[:200],
        source=body.source,
        amount=body.amount,
        currency=body.currency,
        date=body.date,
        status=Charge.Status.PAID if body.paid else Charge.Status.DUE,
        paid_on=today() if body.paid else None,
    )


@transaction.atomic
def refund_booking(tenant_id: str, booking_id: str) -> int:
    """Cancelling a booking refunds what was paid for it and drops what was still owed.

    A dropped charge that sat on an open invoice leaves it: the invoice is totalled again
    (and voided if nothing is left on it).
    """
    rows = Charge.objects.filter(tenant_id=tenant_id, booking_id=booking_id)
    refunded = rows.filter(status=Charge.Status.PAID).update(status=Charge.Status.REFUNDED)
    owed = rows.filter(status=Charge.Status.DUE)
    touched = set(owed.exclude(invoice_id=None).values_list("invoice_id", flat=True))
    owed.delete()
    if touched:
        invoices.retotal(touched)
    return refunded


def balances(tenant_id: str, customer_ids: list[str] | None) -> dict[str, dict[str, str]]:
    rows = Charge.objects.filter(tenant_id=tenant_id)
    if customer_ids is not None:
        rows = rows.filter(customer_id__in=customer_ids)
    out: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"spend": ZERO, "balance": ZERO})
    for r in rows.values("customer_id", "status").annotate(total=Sum("amount")):
        key = "spend" if r["status"] == Charge.Status.PAID else "balance" if r["status"] == Charge.Status.DUE else None
        if key:
            out[str(r["customer_id"])][key] += r["total"]
    return {cid: {k: wire(v) for k, v in m.items()} for cid, m in out.items()}


def customer_charges(tenant_id: str, customer_id: str) -> list[dict[str, Any]]:
    now = today()
    rows = Charge.objects.filter(tenant_id=tenant_id, customer_id=customer_id).order_by("-date", "-created_at")[:12]
    return [charge_dict(c, now) for c in rows]
