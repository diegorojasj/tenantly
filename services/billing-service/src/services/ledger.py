"""The business ledger: expenses and other income beside the charges (models/ledger.py)."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.internal import audit
from common.money import ZERO, label, wire

from ..models import Charge, Entry
from .charges import MONEY, today

if TYPE_CHECKING:
    from datetime import date

    from common.auth import TenantClaims

    from ..schemas import EntryIn, ManualEntryIn

LIST_LIMIT = 300
DEFAULT_DAYS = 30


def entry_dict(e: Entry) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "locationId": str(e.location_id),
        "kind": e.kind,
        "category": e.category,
        "description": e.description,
        "amount": wire(e.amount),
        "currency": e.currency,
        "date": e.date.isoformat(),
        "source": e.source,
        "refId": str(e.ref_id) if e.ref_id else None,
        "charged": e.charged,
        "recordedBy": e.recorded_by,
        "voided": e.voided,
    }


def _sum(rows: Any) -> Decimal:
    return rows.aggregate(s=Sum("amount"))["s"] or ZERO


# ------------------------------------------------------------- reading --


def read(claims: TenantClaims, scope: str | None, start: date | None, end: date | None) -> dict[str, Any]:
    """Entries in scope between `start` and `end` (default: the last 30 days), with the period's totals.

    `net` is revenue (charges not refunded) plus other income minus expenses.
    """
    claims.demand_any(MONEY)
    last = end or today()
    first = start or last - timedelta(days=DEFAULT_DAYS - 1)
    if first > last:
        msg = _("The period must start before it ends")
        raise InvalidError(msg)
    locations = claims.locations(scope)
    rows = Entry.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations, date__gte=first, date__lte=last)
    counted = rows.filter(voided=False, charged=False)
    income = _sum(counted.filter(kind=Entry.Kind.INCOME))
    expense = _sum(counted.filter(kind=Entry.Kind.EXPENSE))
    revenue = _sum(
        Charge.objects.filter(
            tenant_id=claims.tenant_id, location_id__in=locations, date__gte=first, date__lte=last
        ).exclude(status=Charge.Status.REFUNDED)
    )
    by_category: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for r in counted.values("kind", "category").annotate(total=Sum("amount")):
        by_category[r["kind"], r["category"]] += r["total"]
    return {
        "canRecord": claims.can("payments.collect"),
        "currency": claims.currency,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "totals": {
            "revenue": wire(revenue),
            "income": wire(income),
            "expense": wire(expense),
            "net": wire(revenue + income - expense),
        },
        "byCategory": [
            {"kind": kind, "category": category, "amount": wire(total)}
            for (kind, category), total in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
        "entries": [entry_dict(e) for e in rows[:LIST_LIMIT]],
    }


def by_ref(tenant_id: str, ref_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Per downtime (or other ref): its lines and what they add up to, voided lines left out."""
    rows = Entry.objects.filter(tenant_id=tenant_id, ref_id__in=ref_ids, voided=False).order_by("date", "created_at")
    out: dict[str, dict[str, Any]] = {}
    for e in rows:
        ref = out.setdefault(str(e.ref_id), {"income": ZERO, "expense": ZERO, "entries": []})
        ref[e.kind] += e.amount
        ref["entries"].append(entry_dict(e))
    return {k: {**v, "income": wire(v["income"]), "expense": wire(v["expense"])} for k, v in out.items()}


# ------------------------------------------------------------- writing --


def record(body: EntryIn) -> Entry:
    """Idempotent on `key`: replaying the same request returns the line it already recorded."""
    if body.key:
        existing = Entry.objects.filter(tenant_id=body.tenant_id, key=body.key).first()
        if existing:
            return existing
    return Entry.objects.create(
        key=body.key,
        tenant_id=body.tenant_id,
        location_id=body.location_id,
        kind=body.kind,
        category=body.category.strip()[:40] or body.kind,
        description=body.description[:200],
        amount=body.amount,
        currency=body.currency,
        date=body.date,
        source=body.source,
        ref_id=body.ref_id,
        charged=body.charged,
        recorded_by=body.recorded_by[:160],
    )


@transaction.atomic
def add(claims: TenantClaims, body: ManualEntryIn, key: str | None = None) -> Entry:
    claims.demand("payments.collect")
    claims.require_location(body.location_id)
    if key:
        existing = Entry.objects.filter(tenant_id=claims.tenant_id, key=key).first()
        if existing:
            return existing
    category = body.category.strip()
    entry = Entry.objects.create(
        key=key,
        tenant_id=claims.tenant_id,
        location_id=body.location_id,
        kind=body.kind,
        category=category,
        description=body.description.strip()[:200] or category,
        amount=body.amount,
        currency=claims.currency,
        date=body.on or today(),
        source=Entry.Source.MANUAL,
        recorded_by=claims.user_name,
    )
    audit(
        claims,
        f"ledger.{entry.kind}",
        "billing",
        f"{label(entry.amount, entry.currency)} · {entry.category} · {entry.description}",
        body.location_id,
    )
    return entry


@transaction.atomic
def void(claims: TenantClaims, entry_id: str) -> Entry:
    claims.demand("payments.collect")
    entry = Entry.objects.select_for_update().filter(tenant_id=claims.tenant_id, id=entry_id).first()
    if not entry or not claims.reaches(str(entry.location_id)):
        msg = _("That entry is outside your scope")
        raise NotFoundError(msg)
    if entry.voided:
        msg = _("That entry is already void")
        raise InvalidError(msg)
    entry.voided = True
    entry.save(update_fields=["voided"])
    audit(
        claims,
        "ledger.voided",
        "billing",
        f"{label(entry.amount, entry.currency)} · {entry.category} · {entry.description}",
        str(entry.location_id),
    )
    return entry
