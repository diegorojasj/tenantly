"""Resources: the team and the assets that deliver the work, and how busy they are."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.internal import audit

from ..models import Booking, Resource
from . import clock, fulfilment, shape

if TYPE_CHECKING:
    from datetime import datetime

    from common.auth import TenantClaims

    from ..schemas import ResourceIn

MIN_NAME = 2


def _week_share(claims: TenantClaims, r: Resource, minutes: float) -> int:
    """Booked share of a week of the resource's location's opening hours."""
    opens, closes = claims.hours(str(r.location_id))
    open_minutes = (closes - opens) * 7
    return min(100, round(minutes / open_minutes * 100)) if open_minutes else 0


def read(claims: TenantClaims, scope: str | None) -> dict[str, Any]:
    claims.demand_any(("config.write", "analytics.view"))
    locations = claims.locations(scope)
    now = clock.now()
    since = now - timedelta(days=7)
    rows = list(Resource.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations))
    booked: dict[str, float] = {}
    upcoming: dict[str, datetime] = {}
    live = Booking.objects.filter(
        tenant_id=claims.tenant_id, location_id__in=locations, start__gte=since, start__lte=now + timedelta(days=60)
    ).exclude(status=Booking.Status.CANCELLED)
    for b in live.prefetch_related("resources"):
        minutes = (b.end - b.start).total_seconds() / 60
        for r in b.resources.all():
            rid = str(r.id)
            if b.start <= now:
                booked[rid] = booked.get(rid, 0) + minutes
            elif rid not in upcoming or b.start < upcoming[rid]:
                upcoming[rid] = b.start
    return {
        "canEdit": claims.can("config.write"),
        "locations": [
            {"id": n.id, "name": n.name, "kind": n.kind, "parentId": n.parent_id}
            for n in claims.nodes
            if n.id in locations
        ],
        "resources": [
            {
                "resource": shape.resource(r),
                "locationName": claims.name_of(str(r.location_id)),
                "utilization": _week_share(claims, r, booked.get(str(r.id), 0)),
                "next": clock.stamp(upcoming[str(r.id)], claims.zone(str(r.location_id)))
                if str(r.id) in upcoming
                else None,
            }
            for r in rows
        ],
    }


@transaction.atomic
def create(claims: TenantClaims, body: ResourceIn) -> Resource:
    claims.demand("config.write")
    claims.require_location(body.location_id)
    kind = next((t for t in fulfilment.resource_types(claims) if t.get("key") == body.type), None)
    if not kind:
        msg = _("%(business)s businesses have no resource type '%(type)s'") % {
            "business": claims.template.get("label", _("This")),
            "type": body.type,
        }
        raise InvalidError(msg)
    name = body.name.strip()
    role = body.role.strip()
    if len(name) < MIN_NAME:
        msg = _("Enter a name")
        raise InvalidError(msg)
    if not role:
        example = "Yoga" if kind.get("people") else "Kayak"
        msg = _("Enter the %(role)s (for example: %(example)s)") % {
            "role": str(kind.get("roleLabel") or _("type")).lower(),
            "example": example,
        }
        raise InvalidError(msg)
    attributes = fulfilment.attributes(claims, body.type, body.attributes or {})
    parent = None
    if body.parent_id:
        siblings = Resource.objects.filter(tenant_id=claims.tenant_id, location_id=body.location_id)
        parent = next((r for r in siblings if str(r.id) == body.parent_id), None)
        if not parent:
            msg = _("It can only sit inside something at the same location")
            raise InvalidError(msg)
    resource = Resource.objects.create(
        tenant_id=claims.tenant_id,
        location_id=body.location_id,
        type=body.type,
        name=name,
        role=role[:60],
        attributes=attributes,
        parent=parent,
    )
    audit(claims, "resource.created", "config", f"{name} ({role})", body.location_id)
    return resource


@transaction.atomic
def set_status(claims: TenantClaims, resource_id: str, status: str) -> Resource:
    claims.demand("config.write")
    resource = (
        Resource.objects.select_for_update(of=("self",)).filter(tenant_id=claims.tenant_id, id=resource_id).first()
    )
    if not resource or not claims.reaches(str(resource.location_id)):
        msg = _("That resource is outside your scope")
        raise NotFoundError(msg)
    if status not in {"available", "out_of_service"}:
        msg = _("Unknown status")
        raise InvalidError(msg)
    resource.status = status
    resource.save(update_fields=["status"])
    audit(
        claims,
        "resource.restored" if status == "available" else "resource.out_of_service",
        "config",
        resource.name,
        str(resource.location_id),
    )
    return resource
