"""Rows -> the shapes the frontend's types expect (src/lib/types.ts)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from common.money import wire

from . import downtimes, money
from .clock import stamp
from .fields import defs, visible
from .fulfilment import people

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet

    from common.auth import TenantClaims

    from ..models import Booking, Offering, Resource


def with_relations(rows: QuerySet[Booking]) -> QuerySet[Booking]:
    return rows.select_related("offering", "customer", "subject").prefetch_related("resources", "attendances__customer")


def booking(claims: TenantClaims, b: Booking) -> dict[str, Any]:
    team = people(claims)
    resources = sorted(b.resources.all(), key=lambda r: (r.type not in team, r.name))
    attendees = [{"id": str(a.customer_id), "name": a.customer.name} for a in b.attendances.all()]
    tz = claims.zone(str(b.location_id))
    return {
        "id": str(b.id),
        "locationId": str(b.location_id),
        "locationName": claims.name_of(str(b.location_id)),
        "offeringId": str(b.offering_id),
        "offeringName": b.offering.name,
        "kind": b.offering.kind,
        "customerId": str(b.customer_id) if b.customer_id else None,
        "customerName": b.customer.name if b.customer else b.offering.name,
        "attendees": attendees,
        "subjectId": str(b.subject_id) if b.subject_id else None,
        "subjectName": b.subject.name if b.subject else None,
        "fields": visible(claims, defs(claims, "booking"), b.fields),
        "capacity": b.offering.capacity or 1,
        "place": b.offering.place,
        "resourceIds": [str(r.id) for r in resources],
        "resourceNames": [r.name for r in resources],
        # The location's wall clock, and the zone it runs in.
        "start": stamp(b.start, tz),
        "end": stamp(b.end, tz),
        "tz": tz.key,
        "status": b.status,
        "price": wire(b.price),
        "currency": claims.currency,
        "paid": b.paid,
        # The downtime it falls in, when one does (set by `bookings`): the desk moves or cancels it.
        "downtime": None,
    }


def bookings(claims: TenantClaims, rows: Iterable[Booking]) -> list[dict[str, Any]]:
    """Many bookings at once. One charged on completion reads as paid once billing collected it."""
    rows = list(rows)
    owed = [str(b.id) for b in rows if b.customer_id and b.status == "completed" and not b.paid]
    settled = money.settled(claims, owed)
    flagged = downtimes.flags(claims, rows)
    return [
        {
            **booking(claims, b),
            "paid": b.paid or str(b.id) in settled,
            "downtime": downtimes.flag(claims, flagged[b.id]) if b.id in flagged else None,
        }
        for b in rows
    ]


def offering(o: Offering) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "kind": o.kind,
        "name": o.name,
        "category": o.category,
        "minutes": o.minutes,
        "price": wire(o.price),
        "unit": o.unit,
        "capacity": o.capacity,
        "credits": o.credits,
        "time": o.time,
        "place": o.place,
        "requires": [
            {"type": r["type"], "quantity": r["quantity"], "pick": r["pick"], "role": r.get("role"), **_where(r)}
            for r in o.requires
        ],
        "subjectType": o.subject_type or None,
        "fields": dict(o.fields),
        "active": o.active,
    }


def resource(r: Resource) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "locationId": str(r.location_id),
        "type": r.type,
        "name": r.name,
        "role": r.role,
        "attributes": dict(r.attributes),
        "parentId": str(r.parent_id) if r.parent_id else None,
        "status": r.status,
    }


def _where(r: dict[str, Any]) -> dict[str, Any]:
    return {"where": r["where"]} if r.get("where") else {}
