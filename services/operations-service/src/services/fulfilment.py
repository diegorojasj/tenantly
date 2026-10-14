"""Fulfilment rules and resource requirements (docs/PLATFORM.md gaps 3-4).

The template (read from the tenant token) defines the resource types a business
has and the presets an offering starts from. An offering keeps its own copy of
the rules: capacity, time, place and the list of resources each booking takes.

A requirement is `{type, quantity, pick, role, where}`:

- `type` is one of the template's resource type keys;
- `pick` says the desk chooses which ones (a coach, a dentist); otherwise free
  ones are assigned (a kayak, a chair);
- `role` narrows the pool to one category (Kayak, Hygienist) and `where` to
  resources whose attributes equal the given values.

Resources may nest (property → unit) inside one location; a booking holding
either one makes the other busy, and so does a `Downtime` on either one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db.models import Q
from django.utils.translation import gettext as _

from common.errors import ConflictError, InvalidError

from ..models import Booking, Downtime, Resource
from . import fields

if TYPE_CHECKING:
    from datetime import datetime

    from common.auth import TenantClaims

TIMES = ("slot", "window", "span", "none")
PLACES = ("on_site", "at_customer")
# What the price buys, per time rule.
UNITS = {"slot": {"session"}, "window": {"hour"}, "span": {"day", "night", "month"}, "none": {"month", "pack"}}
MAX_QUANTITY = 20


# ------------------------------------------------------------- template --


def resource_types(claims: TenantClaims) -> list[dict[str, Any]]:
    return list(claims.template.get("resourceTypes") or [])


def resource_type(claims: TenantClaims, key: str) -> dict[str, Any]:
    """The template's definition of a resource type; a plain one named after the key if it has none."""
    found = next((t for t in resource_types(claims) if t.get("key") == key), None)
    if found:
        return found
    terms = claims.template.get("terms", {})
    return {"key": key, "label": terms.get(key, key.title()), "plural": key.title(), "people": key == "staff"}


def people(claims: TenantClaims) -> set[str]:
    """Resource types that are team members (chosen by the desk, counted as staff)."""
    types = resource_types(claims)
    keys = {t["key"] for t in types if t.get("people")}
    return keys if types else {"staff"}


def preset(claims: TenantClaims, key: str) -> dict[str, Any] | None:
    return next((p for p in claims.template.get("presets") or [] if p.get("key") == key), None)


def sells_plans(claims: TenantClaims) -> bool:
    return any(p.get("time") == "none" for p in claims.template.get("presets") or [])


# ---------------------------------------------------------- definitions --


def requirements(claims: TenantClaims, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalise an offering's requirement list against the template's resource types."""
    known = {t.get("key") for t in resource_types(claims)}
    clean: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("type") or "")
        kind = resource_type(claims, key)
        if key not in known:
            msg = _("%(business)s businesses have no resource type '%(type)s'") % {
                "business": claims.template.get("label", _("This")),
                "type": key,
            }
            raise InvalidError(msg)
        quantity = int(row.get("quantity") or 0)
        if quantity == 0:
            continue
        if not 0 < quantity <= MAX_QUANTITY:
            msg = _("Ask for between 1 and %(n)s of each resource") % {"n": MAX_QUANTITY}
            raise InvalidError(msg)
        role = str(row.get("role") or "").strip()[:60] or None
        if row.get("named") and not role:
            msg = _("Say which kind of %(resource)s it needs (for example: Kayak)") % {
                "resource": kind["label"].lower()
            }
            raise InvalidError(msg)
        where = row.get("where") or {}
        if not isinstance(where, dict):
            msg = _("Requirement filters must be attribute → value")
            raise InvalidError(msg)
        pick = row.get("pick")
        clean.append(
            {
                "type": key,
                "quantity": quantity,
                "pick": bool(kind.get("people")) if pick is None else bool(pick),
                "role": role,
                **({"where": where} if where else {}),
            }
        )
    return clean


def attributes(claims: TenantClaims, type_key: str, values: dict[str, Any]) -> dict[str, Any]:
    """Validate a resource's attributes against its type's typed fields; unknown keys are refused."""
    return fields.clean(list(resource_type(claims, type_key).get("attributes") or []), values)


# ----------------------------------------------------------- assignment --


@dataclass
class Need:
    """One requirement at one location: who could fill it, and (if the desk picks) who was picked."""

    rule: dict[str, Any]
    label: str
    pool: list[Resource]
    picked: list[Resource] = field(default_factory=list)

    @property
    def quantity(self) -> int:
        return int(self.rule.get("quantity", 1))

    @property
    def what(self) -> str:
        return (self.rule.get("role") or self.label).lower()


def _matches(r: Resource, rule: dict[str, Any]) -> bool:
    if r.type != rule.get("type"):
        return False
    if rule.get("role") and r.role.lower() != str(rule["role"]).lower():
        return False
    return all(r.attributes.get(k) == v for k, v in (rule.get("where") or {}).items())


def families(rows: list[Resource]) -> None:
    """Attach to each resource the ids a booking of it collides with: itself, its ancestors, its descendants."""
    by_id = {r.id: r for r in rows}
    children: dict[Any, list[Any]] = {}
    for r in rows:
        if r.parent_id:
            children.setdefault(r.parent_id, []).append(r.id)
    for r in rows:
        family = {r.id}
        cursor = r.parent_id
        while cursor and cursor not in family:
            family.add(cursor)
            cursor = by_id[cursor].parent_id if cursor in by_id else None
        stack = list(children.get(r.id, []))
        while stack:
            child = stack.pop()
            if child not in family:
                family.add(child)
                stack.extend(children.get(child, []))
        r.family = family  # type: ignore[attr-defined]


def down(resource: Resource, start: datetime, end: datetime) -> Downtime | None:
    """The downtime that takes the resource (or one nested with it) out between `start` and `end`."""
    family = getattr(resource, "family", {resource.id})
    return (
        Downtime.objects.filter(resource_id__in=family, start__lt=end)
        .filter(Q(end__isnull=True) | Q(end__gt=start))
        .first()
    )


def busy(resource: Resource, start: datetime, end: datetime) -> bool:
    family = getattr(resource, "family", {resource.id})
    booked = (
        Booking.objects.filter(resources__id__in=family, start__lt=end, end__gt=start)
        .exclude(status=Booking.Status.CANCELLED)
        .exists()
    )
    return booked or down(resource, start, end) is not None


def needs(
    claims: TenantClaims, rules: list[dict[str, Any]], location_id: str, picks: list[str], *, lock: bool = False
) -> list[Need]:
    """Who can fill each requirement here. Refuses missing picks and empty pools before any time is checked.

    With `lock`, the candidates (and everything nested with them) are locked first,
    so two desks can't both take the last free one.
    """
    rows = list(
        Resource.objects.filter(tenant_id=claims.tenant_id, location_id=location_id, status="available").order_by(
            "name"
        )
    )
    wanted = {str(p) for p in picks if p}
    out: list[Need] = []
    for rule in rules:
        kind = resource_type(claims, rule["type"])
        pool = [r for r in rows if _matches(r, rule)]
        need = Need(rule=rule, label=kind["label"], pool=pool)
        if rule.get("pick"):
            taken = {r.id for n in out for r in n.picked}
            need.picked = [r for r in pool if str(r.id) in wanted and r.id not in taken][: need.quantity]
            if len(need.picked) < need.quantity:
                msg = (
                    _("Pick a %(what)s at this location")
                    if need.quantity == 1
                    else _("Pick a %(what)s at this location (it needs %(n)s)")
                ) % {"what": need.what, "n": need.quantity}
                raise InvalidError(msg)
        elif len(pool) < need.quantity:
            msg = _("No %(what)s is in service here. Add one in Resources") % {"what": need.what}
            raise InvalidError(msg)
        out.append(need)
    families(rows)
    if lock and out:
        ids = {i for n in out for r in (n.picked if n.rule.get("pick") else n.pool) for i in r.family}  # type: ignore[attr-defined]
        list(Resource.objects.select_for_update().filter(id__in=ids).order_by("id").values_list("id", flat=True))
    return out


def take(needs_: list[Need], start: datetime, end: datetime, when: str = "") -> list[Resource]:
    """The resources a booking from `start` to `end` holds; ConflictError when any requirement can't be met.

    `when` words the time in the error ("on Mon 12 Oct at 18:00"); "then" by default.
    """
    held: list[Resource] = []
    for need in needs_:
        if need.rule.get("pick"):
            for r in need.picked:
                out = down(r, start, end)
                if out:
                    msg = _("%(name)s is unavailable %(when)s (%(reason)s)") % {
                        "name": r.name,
                        "when": when or _("then"),
                        "reason": out.get_reason_display().lower(),
                    }
                    raise ConflictError(msg)
                if busy(r, start, end):
                    msg = (
                        _("%(name)s is busy %(when)s") % {"name": r.name, "when": when}
                        if when
                        else _("%(name)s is busy then") % {"name": r.name}
                    )
                    raise ConflictError(msg)
            held.extend(need.picked)
            continue
        chosen: list[Resource] = []
        for r in need.pool:
            if len(chosen) == need.quantity:
                break
            if r not in held and not busy(r, start, end):
                chosen.append(r)
        if len(chosen) < need.quantity:
            msg = (
                _("No %(what)s free %(when)s (it needs %(n)s)") if need.quantity > 1 else _("No %(what)s free %(when)s")
            ) % {"what": need.what, "when": when or _("at that time"), "n": need.quantity}
            raise ConflictError(msg)
        held.extend(chosen)
    return held


def free(needs_: list[Need], start: datetime, end: datetime) -> bool:
    try:
        take(needs_, start, end)
    except ConflictError:
        return False
    return True
