"""The catalog: what a business sells, and the rule each offering books under."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils.translation import gettext as _

from common.errors import ForbiddenError, InvalidError, NotFoundError
from common.internal import audit
from common.money import ZERO, dec, wire

from ..models import Booking, Offering, Resource, Subscription
from . import clock, fields, fulfilment, parties, shape

if TYPE_CHECKING:
    from common.auth import TenantClaims

    from ..schemas import OfferingIn

MIN_NAME = 2
MIN_MINUTES = 15


def read(claims: TenantClaims, scope: str | None) -> dict[str, Any]:
    claims.demand_any(("pricing.write", "analytics.view"))
    locations = claims.locations(scope)
    since = clock.now() - timedelta(days=28)
    done = (
        Booking.objects.filter(
            tenant_id=claims.tenant_id, location_id__in=locations, status=Booking.Status.COMPLETED, start__gte=since
        )
        .select_related("offering")
        .prefetch_related("attendances")
    )
    stats: dict[str, dict[str, Any]] = {}
    for b in done:
        s = stats.setdefault(str(b.offering_id), {"bookings": 0, "revenue": ZERO, "seats": 0})
        s["bookings"] += 1
        seats = len(b.attendances.all())
        s["seats"] += seats
        s["revenue"] += b.price * (seats if b.customer_id is None else 1)
    subscribers: dict[str, int] = {}
    for plan_id in Subscription.objects.filter(
        tenant_id=claims.tenant_id, customer__location_id__in=locations, status=Subscription.Status.ACTIVE
    ).values_list("offering_id", flat=True):
        subscribers[str(plan_id)] = subscribers.get(str(plan_id), 0) + 1

    items = []
    for o in Offering.objects.filter(tenant_id=claims.tenant_id):
        s = stats.get(str(o.id), {"bookings": 0, "revenue": ZERO, "seats": 0})
        is_plan = o.time == Offering.Time.NONE
        fill = None
        if o.shared and s["bookings"]:
            fill = round(s["seats"] / (s["bookings"] * o.capacity) * 100)
        items.append(
            {
                "offering": shape.offering(o),
                "bookings": int(s["bookings"]),
                "revenue": wire(subscribers.get(str(o.id), 0) * o.price if is_plan else s["revenue"]),
                "fill": fill,
                "subscribers": subscribers.get(str(o.id), 0) if is_plan else None,
            }
        )
    # Categories already in use per resource type, to suggest when naming a requirement.
    roles: dict[str, set[str]] = {}
    for type_, role in Resource.objects.filter(tenant_id=claims.tenant_id).values_list("type", "role"):
        roles.setdefault(type_, set()).add(role)
    return {
        "canEdit": claims.can("pricing.write"),
        "roles": {k: sorted(v) for k, v in roles.items()},
        "offerings": items,
    }


def _demand_business_wide(claims: TenantClaims) -> None:
    """Offerings are sold everywhere, so only someone scoped to the whole business may change them."""
    claims.demand("pricing.write")
    home = claims.node(claims.home_scope_id)
    if not home or home.parent_id is not None:
        msg = _("The catalog is shared by every location — ask someone who manages the whole business")
        raise ForbiddenError(msg)


def _rules(claims: TenantClaims, body: OfferingIn) -> dict[str, Any]:
    """The offering's fulfilment rules: the preset's, with whatever the body overrides, checked as a whole."""
    tpl = claims.template
    preset = fulfilment.preset(claims, body.kind)
    if not preset:
        msg = _("%(business)s businesses don't sell %(kind)ss") % {
            "business": tpl.get("label", _("This")),
            "kind": body.kind,
        }
        raise InvalidError(msg)
    units = list(preset.get("units") or ["session"])
    unit = body.unit or units[0]
    if unit not in units:
        msg = _("%(offerings)s are priced by the %(units)s") % {
            "offerings": preset.get("plural", body.kind),
            "units": " / ".join(units),
        }
        raise InvalidError(msg)
    time = preset.get("time", "slot")
    if time in {"window", "span"}:  # hire: by the hour on one day, or by whole days, nights or months
        time = "window" if unit == "hour" else "span"
    if time not in fulfilment.TIMES or unit not in fulfilment.UNITS[time]:
        msg = _("A %(time)s offering can't be priced by the %(unit)s") % {"time": time, "unit": unit}
        raise InvalidError(msg)
    if time == "none":
        return {"time": time, "unit": unit, "capacity": None, "place": "on_site", "requires": [], "subject_type": ""}
    capacity = body.capacity if body.capacity is not None else (preset.get("capacity") or 1)
    if capacity < 1:
        msg = _("Capacity must be at least 1")
        raise InvalidError(msg)
    if capacity > 1 and time != "slot":
        msg = _("Only fixed-length sessions can be shared by several customers")
        raise InvalidError(msg)
    place = body.place or preset.get("place") or "on_site"
    if body.requires is None:
        rows = [dict(r) for r in preset.get("requires") or []]
    else:
        # The preset's `named` flags still apply to requirements of the same type.
        named = {r["type"] for r in preset.get("requires") or [] if r.get("named")}
        rows = [{**r.model_dump(), "named": r.type in named} for r in body.requires]
    requires = fulfilment.requirements(claims, rows)
    subject = body.subject_type if body.subject_type is not None else preset.get("subject") or ""
    if subject and subject not in {t.get("key") for t in parties.subject_types(claims)}:
        msg = _("%(business)s businesses have no subject type '%(type)s'") % {
            "business": tpl.get("label", _("This")),
            "type": subject,
        }
        raise InvalidError(msg)
    if subject and capacity > 1:
        msg = _("Sessions several customers share can't each name a subject")
        raise InvalidError(msg)
    return {
        "time": time,
        "unit": unit,
        "capacity": capacity,
        "place": place,
        "requires": requires,
        "subject_type": subject,
    }


@transaction.atomic
def create(claims: TenantClaims, body: OfferingIn) -> Offering:
    _demand_business_wide(claims)
    rules = _rules(claims, body)
    name = body.name.strip()
    if len(name) < MIN_NAME:
        msg = _("Enter a name")
        raise InvalidError(msg)
    is_plan = rules["time"] == Offering.Time.NONE
    if not is_plan and body.minutes < MIN_MINUTES:
        msg = _("Duration must be at least %(n)s minutes") % {"n": MIN_MINUTES}
        raise InvalidError(msg)
    if rules["unit"] == "pack" and (body.credits or 0) < 1:
        msg = _("A pack needs at least one credit")
        raise InvalidError(msg)
    offering = Offering.objects.create(
        tenant_id=claims.tenant_id,
        kind=body.kind,
        name=name,
        category=(body.category or "").strip() or "General",
        minutes=0 if is_plan else body.minutes,
        price=dec(body.price),
        credits=body.credits if rules["unit"] == "pack" else None,
        fields=fields.clean(fields.defs(claims, "offering"), body.fields),
        **rules,
    )
    audit(claims, "offering.created", "config", f"{offering.name} · {offering.kind}", claims.home_scope_id)
    return offering


@transaction.atomic
def toggle(claims: TenantClaims, offering_id: str) -> Offering:
    _demand_business_wide(claims)
    offering = (
        Offering.objects.select_for_update(of=("self",)).filter(tenant_id=claims.tenant_id, id=offering_id).first()
    )
    if not offering:
        msg = _("Unknown offering")
        raise NotFoundError(msg)
    offering.active = not offering.active
    offering.save(update_fields=["active"])
    audit(
        claims,
        "offering.activated" if offering.active else "offering.retired",
        "config",
        offering.name,
        claims.home_scope_id,
    )
    return offering
