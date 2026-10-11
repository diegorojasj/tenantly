"""The team: who belongs to the business, with which role, where."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils.translation import gettext as _

from common.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError

from ..models import Membership, Node
from ..types.roles import OWNER
from . import accounts, ledger, roles

if TYPE_CHECKING:
    from common.auth import TenantClaims


def _scope_path(claims: TenantClaims, node_id: str) -> str:
    names = [n.name for n in claims.ancestry(node_id)[1:]]
    return " / ".join(names) or _("Entire business")


def _member(claims: TenantClaims, m: Membership) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "userId": str(m.user_id) if m.user_id else None,
        "name": m.user.name if m.user else m.email.split("@")[0],
        "email": m.email,
        "role": m.role,
        "scopeId": str(m.scope_id),
        "scopePath": _scope_path(claims, str(m.scope_id)),
        "mfa": m.mfa,
        "sso": False,
        "lastSeen": m.last_seen.isoformat() if m.last_seen else None,
        "status": m.status,
    }


def list_members(claims: TenantClaims, scope: str | None) -> dict[str, Any]:
    claims.demand_any(("members.invite", "roles.assign"))
    focus = claims.focus(scope)
    rows = Membership.objects.select_related("user").filter(tenant_id=claims.tenant_id).order_by("created_at")
    members = [_member(claims, m) for m in rows]
    return {
        # Assigned somewhere inside the focused subtree.
        "direct": [m for m in members if claims.within(m["scopeId"], focus)],
        # Assigned above it — their access cascades down into this scope.
        "inherited": [m for m in members if m["scopeId"] != focus and claims.within(focus, m["scopeId"])],
        "canAssign": claims.can("roles.assign"),
        "canInvite": claims.can("members.invite"),
        "viewerId": claims.user_id,
        "seats": sum(1 for m in members if m["status"] != Membership.Status.SUSPENDED),
    }


def _check_grant(claims: TenantClaims, new_role: str) -> dict[str, Any]:
    """The business's role `new_role`, if the caller may hand it out."""
    granted = roles.require(claims.tenant_id, new_role)
    if new_role == OWNER and claims.role != OWNER:
        msg = _("Only owners can make someone an owner")
        raise ForbiddenError(msg)
    # Nobody hands out more than they hold, or an invite becomes a privilege escalation.
    roles.check_grant(claims, granted["permissions"], granted["label"])
    return granted


def _audit(claims: TenantClaims, action: str, target: str, scope_id: str) -> None:
    ledger.append(
        claims.tenant_id,
        {
            "actor_id": claims.user_id,
            "actor_name": claims.user_name,
            "action": action,
            "category": "access",
            "target": target,
            "scope_id": scope_id,
            "scope_name": claims.name_of(scope_id),
        },
    )


@transaction.atomic
def invite(claims: TenantClaims, *, email: str, new_role: str, scope_id: str) -> str:
    """Record a pending invite and return its one-time code (shown once, to the inviter)."""
    claims.demand("members.invite")
    email = email.strip().lower()
    if "@" not in email:
        msg = _("Enter a valid email address")
        raise InvalidError(msg)
    granted = _check_grant(claims, new_role)
    if not claims.reaches(scope_id) or not Node.objects.filter(tenant_id=claims.tenant_id, id=scope_id).exists():
        msg = _("Pick a place inside your scope")
        raise ForbiddenError(msg)
    if Membership.objects.filter(tenant_id=claims.tenant_id, email=email).exists():
        msg = _("That person is already on the team")
        raise ConflictError(msg)
    # Always a pending invite, even for an existing account: joining takes the code.
    code, code_hash = accounts.invite_code()
    Membership.objects.create(
        tenant_id=claims.tenant_id,
        email=email,
        role=new_role,
        scope_id=scope_id,
        status=Membership.Status.INVITED,
        invite_hash=code_hash,
    )
    _audit(claims, "member.invited", f"{email} as {granted['label']}", scope_id)
    return code


@transaction.atomic
def change_role(claims: TenantClaims, member_id: str, new_role: str) -> Membership:
    claims.demand("roles.assign")
    membership = Membership.objects.select_related("user").filter(tenant_id=claims.tenant_id, id=member_id).first()
    if not membership or not claims.reaches(str(membership.scope_id)):
        msg = _("That person is outside your scope")
        raise NotFoundError(msg)
    if membership.user_id and str(membership.user_id) == claims.user_id:
        msg = _("You can't change your own role")
        raise ForbiddenError(msg)
    granted = _check_grant(claims, new_role)
    if membership.role == OWNER and claims.role != OWNER:
        msg = _("Only owners can change an owner's role")
        raise ForbiddenError(msg)
    membership.role = new_role
    membership.save(update_fields=["role"])
    who = membership.user.name if membership.user else membership.email
    _audit(claims, "role.changed", f"{who} → {granted['label']}", str(membership.scope_id))
    return membership
