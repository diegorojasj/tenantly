"""Businesses (tenants), their location tree, and entering a workspace."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from zoneinfo import available_timezones

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from common.auth import Node as ClaimNode
from common.auth import TenantClaims, issue
from common.errors import ForbiddenError, InvalidError, NotFoundError
from common.money import is_currency

from ..models import Membership, Node, Role, Template, Tenant
from ..types.roles import OWNER
from . import ledger, plan, roles

if TYPE_CHECKING:
    from ..models import User

MIN_NAME = 2
# The template every business starts from (identity 0010): one for any kind of business.
GENERAL = "general"


@dataclass(frozen=True)
class ClockPatch:
    """A location's time zone and opening hours; `None` leaves a field as it is."""

    tz: str | None = None
    open: int | None = None
    close: int | None = None
    reset_hours: bool = False


# ------------------------------------------------------------ templates --


def templates() -> list[dict[str, Any]]:
    return [t.as_dict() for t in Template.objects.all()]


def template_of(tenant: Tenant) -> Template:
    return Template.objects.get(id=tenant.template_id)


def _location_word(template: Template) -> str:
    """The template's word for a location, in the request's language, for use mid-sentence."""
    return str(template.as_dict()["terms"].get("location") or _("location")).lower()


# --------------------------------------------------------------- shapes --


def tenant_dict(tenant: Tenant, template: Template | None = None) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "slug": tenant.slug,
        "name": tenant.name,
        "industry": tenant.industry,
        "template": (template or template_of(tenant)).as_dict(),
        "hue": tenant.hue,
        "idp": _("Email & password"),
        "residency": tenant.residency,
        "tenantKey": tenant.tenant_key,
        **tenant.money(),
        "logoUrl": tenant.logo_url,
        "customDomain": tenant.custom_domain or "",
    }


def node_dict(node: Node, *, reachable: bool | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(node.id),
        "orgId": str(node.tenant_id),
        "parentId": str(node.parent_id) if node.parent_id else None,
        "kind": node.kind,
        "level": node.level,
        "name": node.name,
        "code": node.code,
        "status": node.status,
        "tz": node.tz,
        "hours": list(node.hours) if node.hours else None,
        "headcount": 0,
    }
    if reachable is not None:
        data["reachable"] = reachable
    return data


# ------------------------------------------------------------- creation --


def _unique_slug(name: str) -> str:
    base = slugify(name)[:40].strip("-") or "business"
    slug = base
    n = 2
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _initials(name: str, size: int = 3) -> str:
    letters = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name))
    return (letters or "X")[:size].upper()


def _audit(tenant: Tenant, user: User, action: str, target: str, scope: Node | None) -> None:
    ledger.append(
        str(tenant.id),
        {
            "actor_id": str(user.id),
            "actor_name": user.name,
            "action": action,
            "category": "access" if action.startswith("member") else "config",
            "target": target,
            "scope_id": str(scope.id) if scope else None,
            "scope_name": scope.name if scope else "",
        },
    )


@transaction.atomic
def create_tenant(
    user: User,
    *,
    name: str,
    industry: str,
    location_name: str,
    currency: str = "USD",
    template_id: str = GENERAL,
) -> Tenant:
    """A new business starts with its org node, one location and its creator as owner. Nothing else."""
    name = name.strip()
    location_name = location_name.strip()
    template = Template.objects.filter(id=template_id).first()
    if not template:
        msg = _("Unknown business template")
        raise InvalidError(msg)
    if len(name) < MIN_NAME:
        msg = _("Enter the business name")
        raise InvalidError(msg)
    if len(location_name) < MIN_NAME:
        msg = _("Name your first %(location)s") % {"location": _location_word(template)}
        raise InvalidError(msg)
    if not is_currency(currency):
        msg = _("Pick a currency")
        raise InvalidError(msg)
    tenant = Tenant.objects.create(
        slug=_unique_slug(name),
        name=name,
        industry=industry.strip()[:160],
        template_id=template_id,
        hue=template.hue,
        currency=currency,
        tenant_key=f"tk_{secrets.token_hex(6)}",
    )
    org = Node.objects.create(tenant=tenant, kind=Node.Kind.ORG, name=name, code=_initials(name))
    location = Node.objects.create(tenant=tenant, parent=org, kind=Node.Kind.LOCATION, name=location_name, code="L01")
    roles.seed(tenant, template)
    Membership.objects.create(
        tenant=tenant, user=user, email=user.email, role=OWNER, scope=org, last_seen=timezone.now()
    )
    _audit(tenant, user, "tenant.created", f"{name} ({template.label})", org)
    _audit(tenant, user, "location.created", location_name, location)
    return tenant


def workspaces(user: User) -> list[dict[str, Any]]:
    rows = (
        Membership.objects.select_related("tenant", "scope")
        .filter(user=user, status=Membership.Status.ACTIVE)
        .order_by("tenant__name")
    )
    by_id = {t.id: t for t in Template.objects.filter(id__in={m.tenant.template_id for m in rows})}
    labels = {(r.tenant_id, r.key): r.label for r in Role.objects.filter(tenant_id__in={m.tenant_id for m in rows})}
    return [
        {
            "tenant": tenant_dict(m.tenant, by_id[m.tenant.template_id]),
            "role": m.role,
            "roleLabel": labels.get((m.tenant_id, m.role), m.role),
            "scopeId": str(m.scope_id),
            "scopeName": _("Whole business") if m.scope.kind == Node.Kind.ORG else m.scope.name,
        }
        for m in rows
    ]


# -------------------------------------------------------------- entering --


def _ancestry(nodes: dict[str, Node], node_id: str) -> list[Node]:
    path: list[Node] = []
    cursor = nodes.get(node_id)
    while cursor:
        path.insert(0, cursor)
        cursor = nodes.get(str(cursor.parent_id)) if cursor.parent_id else None
    return path


def enter(user: User, slug: str, scope: str | None) -> tuple[str, dict[str, Any]]:
    """Prove membership and hand back a tenant token plus everything the shell renders."""
    tenant = Tenant.objects.filter(slug=slug).first()
    if not tenant:
        msg = _("No workspace “%(slug)s”") % {"slug": slug}
        raise NotFoundError(msg)
    membership = Membership.objects.filter(tenant=tenant, user=user, status=Membership.Status.ACTIVE).first()
    if not membership:
        msg = _("You are not a member of %(business)s") % {"business": tenant.name}
        raise ForbiddenError(msg)
    Membership.objects.filter(id=membership.id).update(last_seen=timezone.now())

    nodes = {str(n.id): n for n in tenant.nodes.all()}
    home = str(membership.scope_id)

    def reaches(node_id: str) -> bool:
        return any(str(n.id) == home for n in _ancestry(nodes, node_id))

    focus = scope if scope and scope in nodes and reaches(scope) else home
    # A role removed from under a member (it can't be while held, but never trust that) grants nothing.
    member_role = roles.of(str(tenant.id), membership.role) or {
        "id": membership.role,
        "label": membership.role,
        "summary": "",
        "permissions": [],
        "builtin": False,
    }
    template = template_of(tenant)
    # The plan's name and payment standing, from billing; empty (so: active) if it's down.
    billing = plan.entitlements(str(tenant.id))
    claims = TenantClaims(
        user_id=str(user.id),
        user_name=user.name,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        template_id=tenant.template_id,
        role=membership.role,
        permissions=tuple(member_role["permissions"]),
        home_scope_id=home,
        nodes=tuple(
            ClaimNode(
                id=i,
                parent_id=str(n.parent_id) if n.parent_id else None,
                kind=n.kind,
                name=n.name,
                tz=n.tz,
                hours=n.hours,
            )
            for i, n in nodes.items()
        ),
        template=template.rules(),
        money=tenant.money(),
        billing=billing,
        # Restricted by Tenantly: every service lets them read, nothing more.
        access=user.status,
    )
    context = {
        "tenant": tenant_dict(tenant, template),
        "role": member_role,
        "homeScopeId": home,
        "scopeId": focus,
        "path": [node_dict(n) for n in _ancestry(nodes, focus)],
        "nodes": [node_dict(n, reachable=reaches(i)) for i, n in nodes.items()],
        "seats": tenant.memberships.exclude(status=Membership.Status.SUSPENDED).count(),
        "billing": {"plan": billing.get("plan"), "status": billing.get("status", "active")},
        "restricted": user.status == user.Status.RESTRICTED,
    }
    return issue(claims), context


# ------------------------------------------------------------ the tree --


def levels(template: Template) -> list[dict[str, Any]]:
    """The template's named group levels, top to bottom; one unnamed level if it lists none."""
    return list(template.as_dict()["levels"]) or [{"key": "area", "label": _("Area"), "plural": _("Areas")}]


def _depth(keys: list[str], node: Node) -> int:
    """The business is -1, groups their level's index; a group on a level the template dropped sits last."""
    if node.kind == Node.Kind.ORG:
        return -1
    return keys.index(node.level) if node.level in keys else len(keys) - 1


def _group_level(template: Template, parent: Node, level: str | None) -> dict[str, Any]:
    """The level a new group under `parent` goes on: the one asked for, else the next one down."""
    named = levels(template)
    keys = [lv["key"] for lv in named]
    floor = _depth(keys, parent)
    if level is None:
        if floor + 1 >= len(named):
            msg = _("Nothing groups under %(place)s: add a %(location)s") % {
                "place": parent.name,
                "location": _location_word(template),
            }
            raise InvalidError(msg)
        return named[floor + 1]
    if level not in keys:
        msg = _("Pick one of the levels: %(levels)s") % {"levels": ", ".join(lv["label"] for lv in named)}
        raise InvalidError(msg)
    if keys.index(level) <= floor:
        below = named[keys.index(level)]["plural"]
        msg = _("%(levels)s go above %(place)s, not inside it") % {"levels": below, "place": parent.name}
        raise InvalidError(msg)
    return named[keys.index(level)]


def _code(tenant_id: str, kind: str, name: str) -> str:
    count = Node.objects.filter(tenant_id=tenant_id, kind=kind).count() + 1
    return f"{_initials(name, 2)}{count:02d}" if kind == Node.Kind.REGION else f"L{count:02d}"


def _within_home(claims: TenantClaims, node: Node) -> bool:
    """Walk the live tree (not the token's copy): nodes created a moment ago count too."""
    cursor: Node | None = node
    while cursor:
        if str(cursor.id) == claims.home_scope_id:
            return True
        cursor = cursor.parent
    return False


def _reachable_node(claims: TenantClaims, node_id: str) -> Node:
    node = Node.objects.filter(tenant_id=claims.tenant_id, id=node_id).first() if _is_uuid(node_id) else None
    if not node or not _within_home(claims, node):
        msg = _("That place is outside your scope")
        raise ForbiddenError(msg)
    return node


def _is_uuid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F-]{32,36}", value))


@transaction.atomic
def add_node(claims: TenantClaims, *, parent_id: str, kind: str, name: str, level: str | None = None) -> Node:
    """Groups go under the business or a group on a higher level; locations under either."""
    claims.demand_any(("tenant.manage", "roles.assign"))
    name = name.strip()
    if len(name) < MIN_NAME:
        msg = _("Enter a name")
        raise InvalidError(msg)
    parent = _reachable_node(claims, parent_id)
    if kind not in {Node.Kind.REGION, Node.Kind.LOCATION} or parent.kind == Node.Kind.LOCATION:
        msg = _("Nothing goes inside a location: add it to the business or a group")
        raise InvalidError(msg)
    group = (
        _group_level(Template.objects.get(id=claims.template_id), parent, level) if kind == Node.Kind.REGION else None
    )
    node = Node.objects.create(
        tenant_id=claims.tenant_id,
        parent=parent,
        kind=kind,
        level=group["key"] if group else "",
        name=name,
        code=_code(claims.tenant_id, kind, name),
    )
    ledger.append(
        claims.tenant_id,
        {
            "actor_id": claims.user_id,
            "actor_name": claims.user_name,
            "action": f"{group['key'] if group else 'location'}.created",
            "category": "config",
            "target": name,
            "scope_id": str(node.id),
            "scope_name": name,
        },
    )
    return node


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _clock_changes(node: Node, clock: ClockPatch) -> list[str]:
    """Time zone and opening hours, for locations only. Mutates `node`; returns what changed."""
    wanted = clock.tz is not None or clock.open is not None or clock.close is not None or clock.reset_hours
    if not wanted:
        return []
    if node.kind != Node.Kind.LOCATION:
        msg = _("Only locations have a time zone and opening hours")
        raise InvalidError(msg)
    changes: list[str] = []
    if clock.tz is not None and clock.tz.strip() != node.tz:
        tz = clock.tz.strip()
        if tz not in available_timezones() and tz != "UTC":
            msg = _("“%(tz)s” is not a time zone (use a name like America/New_York)") % {"tz": tz}
            raise InvalidError(msg)
        node.tz = tz
        changes.append(f"time zone {tz}")
    if clock.reset_hours and node.hours:
        node.open = node.close = None
        changes.append("template hours")
    elif clock.open is not None and clock.close is not None and (clock.open, clock.close) != node.hours:
        if clock.close <= clock.open:
            msg = _("Closing time must be after opening time")
            raise InvalidError(msg)
        node.open, node.close = clock.open, clock.close
        changes.append(f"hours {_hhmm(clock.open)} to {_hhmm(clock.close)}")
    return changes


@transaction.atomic
def update_node(
    claims: TenantClaims, node_id: str, *, name: str | None, status: str | None, clock: ClockPatch | None = None
) -> Node:
    claims.demand_any(("tenant.manage", "roles.assign"))
    node = _reachable_node(claims, node_id)
    changes: list[str] = _clock_changes(node, clock) if clock else []
    if name is not None and name.strip() and name.strip() != node.name:
        if len(name.strip()) < MIN_NAME:
            msg = _("Enter a name")
            raise InvalidError(msg)
        changes.append(f"renamed to {name.strip()}")
        node.name = name.strip()
    if status is not None and status != node.status:
        if status not in {"active", "paused"} or node.kind != Node.Kind.LOCATION:
            msg = _("Only locations can be paused")
            raise InvalidError(msg)
        changes.append(status)
        node.status = status
    if changes:
        node.save()
        if node.kind == Node.Kind.ORG:
            Tenant.objects.filter(id=claims.tenant_id).update(name=node.name)
        ledger.append(
            claims.tenant_id,
            {
                "actor_id": claims.user_id,
                "actor_name": claims.user_name,
                "action": "location.updated",
                "category": "config",
                "target": f"{node.name}: {', '.join(changes)}",
                "scope_id": str(node.id),
                "scope_name": node.name,
            },
        )
    return node
