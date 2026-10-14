"""Downtime: when a resource, an offering or a whole location can't be booked, and why.

A repair, maintenance, something unsuitable for use, a team member away or the
site shut. While a window is open nothing new is booked into it: a resource down
is busy (fulfilment.busy), so every offering needing it has no free time either;
an offering or a location down refuses its own bookings. Bookings made before
the window are kept and flagged on Today, Calendar and the booking panel so the
desk reassigns, moves or cancels them (a cancellation then waives the late fee).

What the situation costs (the repair bill) or earns (an insurance payout, damage
charged to a customer) is recorded against it: billing keeps the business ledger.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from common.errors import ConflictError, InvalidError, NotFoundError
from common.internal import audit
from common.money import wire

from ..models import Booking, Customer, Downtime, Offering, Resource
from . import clock, fulfilment, money

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date, datetime

    from common.auth import TenantClaims

    from ..schemas import DowntimeIn, DowntimeMoneyIn

MANAGE = ("config.write", "bookings.manage")
READ = (*MANAGE, "analytics.view")
# Bookings still to be served: the ones a downtime puts in doubt.
LIVE = (Booking.Status.REQUESTED, Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)
PAST_DAYS = 30


def _overlaps(start: datetime, end: datetime | None) -> Q:
    """Downtimes open at some point between `start` and `end` (no `end`: from `start` on)."""
    q = Q(end__isnull=True) | Q(end__gt=start)
    return q & Q(start__lt=end) if end else q


def _hits(d: Downtime, b: Booking, families: dict[Any, set[Any]]) -> bool:
    """Whether the downtime covers the booking: same location and time, and its target is what the booking uses."""
    if d.location_id != b.location_id or b.end <= d.start or (d.end and b.start >= d.end):
        return False
    if d.offering_id:
        return d.offering_id == b.offering_id
    if d.resource_id:
        family = families.get(d.resource_id, {d.resource_id})
        return any(r.id in family for r in b.resources.all())
    return True


def _families(tenant_id: str, location_ids: Iterable[Any]) -> dict[Any, set[Any]]:
    rows = list(Resource.objects.filter(tenant_id=tenant_id, location_id__in=set(location_ids)))
    fulfilment.families(rows)
    return {r.id: r.family for r in rows}  # type: ignore[attr-defined]


def label(claims: TenantClaims, d: Downtime) -> str:
    """What is down: the resource, the offering, or the location."""
    if d.resource_id:
        return d.resource.name
    if d.offering_id:
        return d.offering.name
    return claims.name_of(str(d.location_id))


def describe(claims: TenantClaims, d: Downtime) -> str:
    """ "Kayak 3 · repair until 2026-10-14 18:00", for errors and alerts."""
    tz = claims.zone(str(d.location_id))
    until = (
        _("until %(when)s") % {"when": clock.stamp(d.end, tz).replace("T", " ")} if d.end else _("until further notice")
    )
    return f"{label(claims, d)} · {d.get_reason_display().lower()} {until}"


# --------------------------------------------------------------- blocking --


def windows(
    claims: TenantClaims, location_id: str, offering: Offering, start: datetime, end: datetime
) -> list[Downtime]:
    """Location-wide and offering downtimes at the location open between `start` and `end`."""
    return list(
        Downtime.objects.filter(tenant_id=claims.tenant_id, location_id=location_id, resource__isnull=True)
        .filter(Q(offering__isnull=True) | Q(offering=offering))
        .filter(_overlaps(start, end))
        .select_related("offering")
    )


def closing(rows: list[Downtime], start: datetime, end: datetime) -> Downtime | None:
    """Of `windows`' rows, the first open between `start` and `end`."""
    return next((d for d in rows if d.start < end and (d.end is None or d.end > start)), None)


def demand_open(claims: TenantClaims, location_id: str, offering: Offering, start: datetime, end: datetime) -> None:
    """Refuse a booking of `offering` from `start` to `end` while it or its location is down."""
    found = closing(windows(claims, location_id, offering, start, end), start, end)
    if found:
        msg = _("Unavailable then: %(what)s") % {"what": describe(claims, found)}
        raise ConflictError(msg)


def covering(claims: TenantClaims, booking: Booking) -> Downtime | None:
    """The downtime a booking falls in, if any."""
    found = flags(claims, [booking])
    return found.get(booking.id)


def flags(claims: TenantClaims, rows: list[Booking]) -> dict[Any, Downtime]:
    """For each live booking among `rows` that a downtime covers: that downtime.

    `rows` must have their resources prefetched (shape.with_relations does).
    """
    live = [b for b in rows if b.status in LIVE]
    if not live:
        return {}
    locations = {b.location_id for b in live}
    downs = list(
        Downtime.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations)
        .filter(_overlaps(min(b.start for b in live), max(b.end for b in live)))
        .select_related("resource", "offering")
    )
    if not downs:
        return {}
    families = _families(claims.tenant_id, locations) if any(d.resource_id for d in downs) else {}
    out: dict[Any, Downtime] = {}
    for b in live:
        hit = next((d for d in downs if _hits(d, b, families)), None)
        if hit:
            out[b.id] = hit
    return out


def flag(claims: TenantClaims, d: Downtime) -> dict[str, Any]:
    """How a flagged booking names the downtime it falls in."""
    return {"id": str(d.id), "reason": d.reason, "what": label(claims, d), "target": d.target}


# ---------------------------------------------------------------- reading --


def _clashes(claims: TenantClaims, d: Downtime, families: dict[Any, set[Any]]) -> list[dict[str, Any]]:
    rows = (
        Booking.objects.filter(
            tenant_id=claims.tenant_id, location_id=d.location_id, status__in=LIVE, end__gt=max(d.start, clock.now())
        )
        .filter(Q(start__lt=d.end) if d.end else Q())
        .select_related("offering", "customer")
        .prefetch_related("resources")
    )
    tz = claims.zone(str(d.location_id))
    return [
        {
            "id": str(b.id),
            "offeringName": b.offering.name,
            "customerName": b.customer.name if b.customer else b.offering.name,
            "start": clock.stamp(b.start, tz),
            "status": b.status,
        }
        for b in rows
        if _hits(d, b, families)
    ]


def shape(claims: TenantClaims, d: Downtime, families: dict[Any, set[Any]], ledger: dict[str, Any]) -> dict[str, Any]:
    tz = claims.zone(str(d.location_id))
    now = clock.now()
    return {
        "id": str(d.id),
        "locationId": str(d.location_id),
        "locationName": claims.name_of(str(d.location_id)),
        "target": d.target,
        "resourceId": str(d.resource_id) if d.resource_id else None,
        "offeringId": str(d.offering_id) if d.offering_id else None,
        "what": label(claims, d),
        "reason": d.reason,
        "note": d.note,
        "start": clock.stamp(d.start, tz),
        "end": clock.stamp(d.end, tz) if d.end else None,
        "tz": tz.key,
        "state": "upcoming" if d.start > now else "over" if d.end and d.end <= now else "now",
        "recordedBy": d.recorded_by,
        "clashes": _clashes(claims, d, families) if not d.end or d.end > now else [],
        # Billing's ledger lines recorded against it (best effort: empty when billing can't answer).
        "money": ledger.get(str(d.id)) or {"income": "0.00", "expense": "0.00", "entries": []},
    }


def read(claims: TenantClaims, scope: str | None) -> dict[str, Any]:
    """Current and upcoming downtimes in scope, and those that ended in the last 30 days."""
    claims.demand_any(READ)
    locations = claims.locations(scope)
    since = clock.now() - timedelta(days=PAST_DAYS)
    rows = list(
        Downtime.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations)
        .filter(Q(end__isnull=True) | Q(end__gt=since))
        .select_related("resource", "offering")
        .order_by("-start")
    )
    families = _families(claims.tenant_id, {d.location_id for d in rows}) if rows else {}
    ledger = money.ledger_for(claims, [str(d.id) for d in rows]) if rows else {}
    return {
        "canEdit": any(claims.can(p) for p in MANAGE),
        "canRecordMoney": claims.can("payments.collect"),
        "currency": claims.currency,
        "reasons": [{"key": k, "label": str(v)} for k, v in Downtime.Reason.choices],
        "downtimes": [shape(claims, d, families, ledger) for d in rows],
    }


def at(claims: TenantClaims, location_id: str, first: datetime, last: datetime) -> list[dict[str, Any]]:
    """Downtimes at one location open between `first` and `last`, for the calendar's timeline."""
    tz = claims.zone(location_id)
    rows = Downtime.objects.filter(tenant_id=claims.tenant_id, location_id=location_id).filter(_overlaps(first, last))
    return [
        {
            "id": str(d.id),
            "target": d.target,
            "resourceId": str(d.resource_id) if d.resource_id else None,
            "offeringId": str(d.offering_id) if d.offering_id else None,
            "reason": d.reason,
            "note": d.note,
            "start": clock.stamp(max(d.start, first), tz),
            "end": clock.stamp(min(d.end, last) if d.end else last, tz),
        }
        for d in rows
    ]


def current(claims: TenantClaims, locations: set[str]) -> list[Downtime]:
    """Downtimes open right now in these locations."""
    now = clock.now()
    return list(
        Downtime.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations, start__lte=now)
        .filter(Q(end__isnull=True) | Q(end__gt=now))
        .select_related("resource", "offering")
    )


# ---------------------------------------------------------------- writing --


def _get(claims: TenantClaims, downtime_id: str) -> Downtime:
    found = (
        Downtime.objects.select_for_update(of=("self",))
        .select_related("resource", "offering")
        .filter(tenant_id=claims.tenant_id, id=downtime_id)
        .first()
    )
    if not found or not claims.reaches(str(found.location_id)):
        msg = _("That downtime is outside your scope")
        raise NotFoundError(msg)
    return found


@transaction.atomic
def create(claims: TenantClaims, body: DowntimeIn) -> Downtime:
    claims.demand_any(MANAGE)
    resource = offering = None
    if body.resource_id and body.offering_id:
        msg = _("Take out a resource or an offering, not both")
        raise InvalidError(msg)
    if body.resource_id:
        resource = Resource.objects.filter(tenant_id=claims.tenant_id, id=body.resource_id).first()
        if not resource or not claims.reaches(str(resource.location_id)):
            msg = _("That resource is outside your scope")
            raise NotFoundError(msg)
        location_id = str(resource.location_id)
    else:
        if not body.location_id:
            msg = _("Pick a location")
            raise InvalidError(msg)
        location_id = body.location_id
        claims.require_location(location_id)
        if body.offering_id:
            offering = Offering.objects.filter(tenant_id=claims.tenant_id, id=body.offering_id).first()
            if not offering or offering.time == Offering.Time.NONE:
                msg = _("Pick something that can be booked")
                raise InvalidError(msg)
    tz = claims.zone(location_id)
    start = clock.parse_stamp(body.start, tz) if body.start else clock.now()
    end = clock.parse_stamp(body.end, tz) if body.end else None
    if end and end <= start:
        msg = _("It must end after it starts")
        raise InvalidError(msg)
    if end and end <= clock.now():
        msg = _("That time has already passed")
        raise InvalidError(msg)
    downtime = Downtime.objects.create(
        tenant_id=claims.tenant_id,
        location_id=location_id,
        resource=resource,
        offering=offering,
        reason=body.reason,
        note=body.note.strip()[:300],
        start=start,
        end=end,
        recorded_by=claims.user_name,
    )
    audit(claims, "downtime.created", "config", describe(claims, downtime), location_id)
    return downtime


@transaction.atomic
def finish(claims: TenantClaims, downtime_id: str) -> Downtime | None:
    """Back in use now. One that hasn't started yet is withdrawn instead (and None returned)."""
    claims.demand_any(MANAGE)
    downtime = _get(claims, downtime_id)
    now = clock.now()
    words = describe(claims, downtime)
    if downtime.start > now:
        downtime.delete()
        audit(claims, "downtime.withdrawn", "config", words, str(downtime.location_id))
        return None
    if downtime.end and downtime.end <= now:
        msg = _("That downtime is already over")
        raise InvalidError(msg)
    downtime.end = now
    downtime.save(update_fields=["end"])
    audit(claims, "downtime.ended", "config", words, str(downtime.location_id))
    return downtime


@transaction.atomic
def record_money(claims: TenantClaims, downtime_id: str, body: DowntimeMoneyIn) -> None:
    """An expense (the repair bill) or an income (an insurance payout) for the business ledger.

    Income from a customer (damage they caused) is raised as a charge on them
    instead, so it shows on their balance and can be invoiced and collected.
    """
    claims.demand("payments.collect")
    downtime = _get(claims, downtime_id)
    location_id = str(downtime.location_id)
    on: date = body.on or clock.today(claims.zone(location_id))
    description = body.description.strip()[:200] or f"{downtime.get_reason_display()} · {label(claims, downtime)}"
    if body.customer_id:
        if body.kind != "income":
            msg = _("Only income can be charged to a customer")
            raise InvalidError(msg)
        customer = Customer.objects.filter(tenant_id=claims.tenant_id, id=body.customer_id).first()
        if not customer or not claims.reaches(str(customer.location_id)):
            msg = _("Pick a %(customer)s") % {"customer": claims.template["terms"]["customer"].lower()}
            raise InvalidError(msg)
        money.raise_charge(
            claims,
            customer,
            location_id=location_id,
            description=description,
            source="fee",
            amount=body.amount,
            on=on,
            paid=False,
        )
    money.record_entry(
        claims,
        location_id=location_id,
        kind=body.kind,
        category=body.category or downtime.reason,
        description=description,
        amount=body.amount,
        on=on,
        ref=str(downtime.id),
        # Charged to a customer: the charge is the money; the line only ties it to the downtime.
        charged=bool(body.customer_id),
    )
    audit(
        claims,
        f"downtime.{body.kind}",
        "billing",
        f"{wire(body.amount)} {claims.currency} · {description}",
        location_id,
    )


def refuse_seat(claims: TenantClaims, session: Booking) -> None:
    """Nobody joins a session a downtime has put in doubt."""
    found = covering(claims, session)
    if found:
        msg = _("Unavailable then: %(what)s") % {"what": describe(claims, found)}
        raise ConflictError(msg)
