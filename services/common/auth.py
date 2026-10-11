"""Tenant tokens: how a request proves who it is and what it may touch.

The identity service issues a short-lived JWT per (user, tenant) after checking
membership. It carries the role's permissions and the member's slice of the
location tree, so every other service can authorize and scope a request
without calling identity again. It also carries the rules of the tenant's
business template (vocabulary, lifecycle, hours, policy defaults), so no
service needs its own copy of the registry identity owns. Location nodes carry
their time zone and opening hours, and the tenant's currency and tax settings
ride along as `money`. Services trust nothing else: the tenant id
on every query comes from the token, never from the request body.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jwt
from django.conf import settings
from django.utils.translation import gettext as _
from ninja.security import HttpBearer

from .errors import ForbiddenError, UnauthenticatedError

if TYPE_CHECKING:
    from django.http import HttpRequest

ISSUER = "tenantly-identity"
AUDIENCE = "tenantly"
TOKEN_TTL_SECONDS = 300
UTC_ZONE = ZoneInfo("UTC")


def _secret() -> str:
    secret = getattr(settings, "JWT_SECRET", "")
    if not secret:
        msg = "JWT_SECRET is not set"
        raise RuntimeError(msg)
    return secret


@dataclass(frozen=True)
class Node:
    id: str
    parent_id: str | None
    kind: str
    name: str
    # Locations only: IANA zone their wall clock runs in, and opening hours
    # (minutes from local midnight) that override the template's.
    tz: str = "UTC"
    hours: tuple[int, int] | None = None

    def wire(self) -> list[Any]:
        """`[id, parent, kind, name]`, plus `tz, hours` only when they differ from the defaults."""
        row: list[Any] = [self.id, self.parent_id, self.kind, self.name]
        if self.tz != "UTC" or self.hours:
            row += [self.tz, list(self.hours) if self.hours else None]
        return row

    @classmethod
    def unwire(cls, row: list[Any]) -> Node:
        """Reads both the four-item rows older tokens carry and the six-item ones."""
        extra = [*row[4:6], None, None]
        hours = (int(extra[1][0]), int(extra[1][1])) if extra[1] else None
        return cls(id=row[0], parent_id=row[1], kind=row[2], name=row[3], tz=extra[0] or "UTC", hours=hours)


@dataclass(frozen=True)
class TenantClaims:
    user_id: str
    user_name: str
    tenant_id: str
    tenant_slug: str
    template_id: str
    role: str
    permissions: tuple[str, ...]
    home_scope_id: str
    nodes: tuple[Node, ...] = field(default_factory=tuple)
    # The template's rules (identity's `Template.rules()`): camelCase keys, as on the wire.
    template: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
    # The tenant's money settings (identity's `Tenant.money()`): currency, taxRate, taxLabel, pricesIncludeTax.
    money: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    # ------------------------------------------------------------ authorization

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def demand(self, permission: str) -> None:
        if not self.can(permission):
            msg = _("Your role can't do this (%(permission)s)") % {"permission": permission}
            raise ForbiddenError(msg)

    def demand_any(self, permissions: tuple[str, ...]) -> None:
        if not any(self.can(p) for p in permissions):
            msg = _("Your role doesn't use this page")
            raise ForbiddenError(msg)

    # ------------------------------------------------------------------ scope

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def ancestry(self, node_id: str) -> list[Node]:
        """Root -> node, inclusive. Empty when the node isn't in this token."""
        path: list[Node] = []
        cursor = self.node(node_id)
        while cursor:
            path.insert(0, cursor)
            cursor = self.node(cursor.parent_id) if cursor.parent_id else None
        return path

    def within(self, node_id: str, ancestor_id: str) -> bool:
        return any(n.id == ancestor_id for n in self.ancestry(node_id))

    def reaches(self, node_id: str) -> bool:
        return self.within(node_id, self.home_scope_id)

    def focus(self, scope: str | None) -> str:
        """The requested scope if the member may open it; their home scope otherwise."""
        return scope if scope and self.reaches(scope) else self.home_scope_id

    def subtree(self, scope: str | None) -> set[str]:
        root = self.focus(scope)
        return {n.id for n in self.nodes if self.within(n.id, root)}

    def locations(self, scope: str | None) -> set[str]:
        ids = self.subtree(scope)
        return {n.id for n in self.nodes if n.id in ids and n.kind == "location"}

    def require_location(self, location_id: str) -> Node:
        node = self.node(location_id)
        if not node or node.kind != "location" or not self.reaches(location_id):
            msg = _("Pick a location inside your scope")
            raise ForbiddenError(msg)
        return node

    def name_of(self, node_id: str | None) -> str:
        node = self.node(node_id) if node_id else None
        return node.name if node else "—"

    # --------------------------------------------------------------- template

    def zone(self, location_id: str | None) -> ZoneInfo:
        """The location's time zone; UTC for anything that isn't a known location."""
        node = self.node(location_id) if location_id else None
        try:
            return ZoneInfo(node.tz) if node else UTC_ZONE
        except (ZoneInfoNotFoundError, ValueError):
            return UTC_ZONE

    def hours(self, location_id: str | None) -> tuple[int, int]:
        """Opening hours (minutes from local midnight): the location's own, else the template's."""
        node = self.node(location_id) if location_id else None
        if node and node.hours:
            return node.hours
        return int(self.template.get("open", 0)), int(self.template.get("close", 24 * 60))

    @property
    def currency(self) -> str:
        """The tenant's ISO 4217 currency; older tokens without money settings mean USD."""
        return str(self.money.get("currency") or "USD")

    def moves(self, status: str) -> list[str]:
        """Statuses a booking in `status` may move to, per the template's lifecycle."""
        return list(self.template.get("transitions", {}).get(status, []))


def issue(claims: TenantClaims, ttl: int = TOKEN_TTL_SECONDS) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + ttl,
        "sub": claims.user_id,
        "name": claims.user_name,
        "tid": claims.tenant_id,
        "tslug": claims.tenant_slug,
        "tpl": claims.template_id,
        "role": claims.role,
        "perms": list(claims.permissions),
        "home": claims.home_scope_id,
        "nodes": [n.wire() for n in claims.nodes],
        "rules": claims.template,
        "money": claims.money,
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def verify(token: str) -> TenantClaims:
    try:
        data = jwt.decode(token, _secret(), algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER)
    except jwt.PyJWTError as exc:
        msg = _("Your session expired — sign in again")
        raise UnauthenticatedError(msg) from exc
    return TenantClaims(
        user_id=data["sub"],
        user_name=data.get("name", ""),
        tenant_id=data["tid"],
        tenant_slug=data["tslug"],
        template_id=data["tpl"],
        role=data["role"],
        permissions=tuple(data["perms"]),
        home_scope_id=data["home"],
        nodes=tuple(Node.unwire(n) for n in data["nodes"]),
        template=data.get("rules") or {},
        money=data.get("money") or {},
    )


class TenantAuth(HttpBearer):
    """`Authorization: Bearer <tenant token>` -> `request.auth` is a TenantClaims."""

    def authenticate(self, request: HttpRequest, token: str) -> TenantClaims:  # noqa: ARG002
        return verify(token)


def claims_of(request: HttpRequest) -> TenantClaims:
    claims = getattr(request, "auth", None)
    if not isinstance(claims, TenantClaims):
        msg = _("Sign in to continue")
        raise UnauthenticatedError(msg)
    return claims
