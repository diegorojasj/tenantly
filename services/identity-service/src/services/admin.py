"""The Tenantly admin console: business owners, their businesses' subscriptions, plans and policy.

Admins are the only way in for an owner: there's no public sign-up, so an admin creates each
owner's account together with their first business and the plan it starts on, and opens any
further business for them. The owner then creates their team's accounts, which ride on the
business's subscription.

Only a `PlatformAdmin` inside an open access window gets here (services/admins.py). An owner
is anyone holding an active `owner` membership; employees and invited members are never
listed. Subscriptions, plan prices and the billing policy are owned by billing: reads come
from it (the owners list in one batch, failing open to no billing data), and changes are
forwarded to it signed by the admin, after the window is checked once more. Every change
lands in the admin audit log with what it looked like before and after.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils.translation import gettext as _

from common.errors import ApiError, NotFoundError
from common.internal import call

from ..models import AdminAuditEvent, Membership, Session, Tenant, User
from ..types.roles import OWNER
from . import accounts, admins, ledger, tenants

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from ..models import PlatformAdmin
    from ..schemas import (
        AdminGrantIn,
        AdminPlanIn,
        BusinessIn,
        InvoicePaidIn,
        OwnerIn,
        OwnerStatusIn,
        PolicyIn,
        RepriceIn,
        TenantIn,
    )

log = logging.getLogger(__name__)

PAGE = 50
MAX_QUERY = 100
OWNER_ACTIONS = {
    User.Status.ACTIVE: "owner.reactivated",
    User.Status.RESTRICTED: "owner.restricted",
    User.Status.SUSPENDED: "owner.suspended",
}


def _owned(user: Any = None) -> QuerySet[Membership]:
    rows = Membership.objects.filter(role=OWNER, status=Membership.Status.ACTIVE)
    return rows.filter(user=user) if user is not None else rows


def _action(admin: PlatformAdmin, ip: str, action: str, target: tuple[str, str], before: Any, after: Any) -> None:
    admins.record(admin, AdminAuditEvent.Kind.ACTION, action=action, target=target, before=before, after=after, ip=ip)


def _forward(admin: PlatformAdmin, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Billing work, signed by the admin; refused if their window closed since the request began."""
    admins.demand_open(admin)
    return call("billing", method, path, json={**(body or {}), "actor": admins.actor(admin)})


# --------------------------------------------------------------- owners --


def _owners(query: str) -> QuerySet[User]:
    owners = User.objects.filter(Exists(_owned(OuterRef("pk"))))
    query = query.strip()[:MAX_QUERY]
    if query:
        owns_match = _owned(OuterRef("pk")).filter(tenant__name__icontains=query)
        owners = owners.filter(Q(name__icontains=query) | Q(email__icontains=query) | Exists(owns_match))
    return owners.order_by("-created_at", "email")


def summaries(tenant_ids: list[str]) -> dict[str, Any] | None:
    """Billing's line per business in one call; None when billing can't be reached."""
    if not tenant_ids:
        return {}
    try:
        return call("billing", "POST", "/internal/admin/summaries", json={"tenantIds": tenant_ids})
    except (ApiError, RuntimeError) as exc:
        log.warning("billing summaries unavailable: %s", exc)
        return None


def _owner_dict(user: User, businesses: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "createdAt": user.created_at.isoformat(),
        "status": user.status,
        "statusChangedAt": user.status_changed_at.isoformat() if user.status_changed_at else None,
        "businesses": businesses,
    }


def _businesses(users: list[User], billing: dict[str, Any] | None) -> dict[Any, list[dict[str, Any]]]:
    owned = list(_owned().filter(user__in=users).select_related("tenant").order_by("tenant__name"))
    members = dict(
        Membership.objects.filter(tenant_id__in={m.tenant_id for m in owned}, status=Membership.Status.ACTIVE)
        .values("tenant_id")
        .annotate(n=Count("id"))
        .values_list("tenant_id", "n")
    )
    out: dict[Any, list[dict[str, Any]]] = {u.id: [] for u in users}
    for m in owned:
        out[m.user_id].append(
            {
                "id": str(m.tenant_id),
                "slug": m.tenant.slug,
                "name": m.tenant.name,
                "createdAt": m.tenant.created_at.isoformat(),
                "members": members.get(m.tenant_id, 0),
                "billing": (billing or {}).get(str(m.tenant_id)),
            }
        )
    return out


def owners(query: str = "", offset: int = 0) -> dict[str, Any]:
    found = _owners(query)
    offset = max(0, offset)
    page = list(found[offset : offset + PAGE])
    tenant_ids = sorted({str(t) for t in _owned().filter(user__in=page).values_list("tenant_id", flat=True)})
    billing = summaries(tenant_ids)
    businesses = _businesses(page, billing)
    return {
        "owners": [_owner_dict(u, businesses[u.id]) for u in page],
        "total": found.count(),
        "offset": offset,
        "limit": PAGE,
        "billingAvailable": billing is not None,
    }


def _uuid(value: str, missing: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as e:
        raise NotFoundError(missing) from e


def _owner(user_id: str) -> User:
    missing = _("No business owner with that id")
    user = User.objects.select_for_update().filter(id=_uuid(user_id, missing)).first()
    if not user or not _owned(user).exists():
        raise NotFoundError(missing)
    return user


def _audit_owned(admin: PlatformAdmin, user: User, action: str) -> None:
    actor = admins.actor(admin)
    for tenant_id in _owned(user).values_list("tenant_id", flat=True):
        ledger.append(
            str(tenant_id),
            {
                "actor_id": actor["id"],
                "actor_name": actor["name"],
                "action": action,
                "category": "security",
                "target": f"{user.name} <{user.email}>",
            },
        )


def set_owner_status(admin: PlatformAdmin, ip: str, user_id: str, body: OwnerStatusIn) -> dict[str, Any]:
    """Active, restricted (signs in, read-only everywhere) or suspended (no sign-in, sessions ended).

    Their businesses keep running for everyone else either way. A restriction reaches the owner
    with their next tenant token (at most five minutes).
    """
    # Outside the transaction: a window found closed is recorded as such, not rolled back.
    admins.demand_open(admin)
    return _set_owner_status(admin, ip, user_id, body)


@transaction.atomic
def _set_owner_status(admin: PlatformAdmin, ip: str, user_id: str, body: OwnerStatusIn) -> dict[str, Any]:
    user = _owner(user_id)
    before = {"status": user.status}
    if user.status != body.status:
        user.status = body.status
        user.status_changed_at = admins.now()
        user.save(update_fields=["status", "status_changed_at"])
        _audit_owned(admin, user, OWNER_ACTIONS[body.status])
    if user.status == User.Status.SUSPENDED:
        Session.objects.filter(user=user).delete()
    after = {"status": user.status, "reason": body.reason}
    _action(admin, ip, "owner.status", ("user", str(user.id)), before, after)
    return _owner_dict(user, [])


# ------------------------------------------------------ creating owners --

# The legacy plan field billing imports when it can't be told the plan right away.
TIER_NAMES = {"starter": "Starter", "growth": "Growth", "enterprise": "Enterprise"}


def _open_business(owner: User, body: TenantIn, plan: str) -> Tenant:
    tenant = tenants.create_tenant(
        owner,
        name=body.name,
        template_id=body.template_id,
        industry=body.industry,
        location_name=body.location_name,
        currency=body.currency,
    )
    tenant.plan = TIER_NAMES[plan]
    tenant.save(update_fields=["plan"])
    return tenant


def _subscribe(admin: PlatformAdmin, tenant: Tenant, plan: str, reason: str) -> bool:
    """Start the business's subscription on `plan`; False if billing can't be reached.

    Nothing is lost then: billing creates the subscription from `Tenant.plan` on first use.
    """
    try:
        _forward(admin, "PUT", f"/internal/tenants/{tenant.id}/plan", {"plan": plan, "terms": None, "reason": reason})
    except (ApiError, RuntimeError) as exc:
        log.warning("billing couldn't start %s's subscription: %s", tenant.id, exc)
        return False
    return True


def _business_dict(tenant: Tenant, plan: str, *, billed: bool) -> dict[str, Any]:
    return {"id": str(tenant.id), "slug": tenant.slug, "name": tenant.name, "plan": plan, "billingPending": not billed}


def create_owner(admin: PlatformAdmin, ip: str, body: OwnerIn) -> dict[str, Any]:
    """A business owner's account, their first business, and the plan it starts on."""
    admins.demand_open(admin)
    with transaction.atomic():
        user = accounts.create_account(body.name, body.email, body.password)
        tenant = _open_business(user, body.business, body.plan)
        after = {"email": user.email, "business": tenant.name, "plan": body.plan, "reason": body.reason}
        _action(admin, ip, "owner.created", ("user", str(user.id)), None, after)
    billed = _subscribe(admin, tenant, body.plan, body.reason)
    return {**_owner_dict(user, []), "business": _business_dict(tenant, body.plan, billed=billed)}


def add_business(admin: PlatformAdmin, ip: str, user_id: str, body: BusinessIn) -> dict[str, Any]:
    """Another business for an owner, with its own subscription."""
    admins.demand_open(admin)
    with transaction.atomic():
        user = _owner(user_id)
        tenant = _open_business(user, body.business, body.plan)
        after = {"business": tenant.name, "plan": body.plan, "reason": body.reason}
        _action(admin, ip, "business.created", ("tenant", str(tenant.id)), None, after)
    billed = _subscribe(admin, tenant, body.plan, body.reason)
    return _business_dict(tenant, body.plan, billed=billed)


# ------------------------------------------------- business subscriptions --


def _business(tenant_id: str) -> str:
    missing = _("Unknown tenant")
    key = _uuid(tenant_id, missing)
    if not Tenant.objects.filter(id=key).exists():
        raise NotFoundError(missing)
    return str(key)


def subscription(tenant_id: str) -> dict[str, Any]:
    return call("billing", "GET", f"/internal/tenants/{_business(tenant_id)}/subscription")


def assign_plan(admin: PlatformAdmin, ip: str, tenant_id: str, body: AdminPlanIn) -> dict[str, Any]:
    terms = body.terms.model_dump(mode="json", by_alias=True, exclude_none=True) if body.terms else None
    key = _business(tenant_id)
    done = _forward(
        admin, "PUT", f"/internal/tenants/{key}/plan", {"plan": body.plan, "terms": terms, "reason": body.reason}
    )
    after = {"plan": done.get("plan"), "status": done.get("status"), "terms": terms, "reason": body.reason}
    _action(admin, ip, "subscription.plan", ("tenant", key), done.get("before"), after)
    return done


def grant(admin: PlatformAdmin, ip: str, tenant_id: str, body: AdminGrantIn) -> dict[str, Any]:
    key = _business(tenant_id)
    done = _forward(admin, "POST", f"/internal/tenants/{key}/grants", body.model_dump(mode="json", by_alias=True))
    _action(admin, ip, "subscription.grant", ("tenant", key), None, done)
    return done


def invoice_paid(admin: PlatformAdmin, ip: str, invoice_id: str, body: InvoicePaidIn) -> dict[str, Any]:
    key = str(_uuid(invoice_id, _("No such Tenantly invoice")))
    done = _forward(admin, "POST", f"/internal/plan-invoices/{key}/paid", {"reference": body.reference})
    before = done.pop("before", None)
    _action(
        admin,
        ip,
        "invoice.paid",
        ("plan_invoice", key),
        before,
        {"status": done.get("status"), "reference": body.reference},
    )
    return done


# ------------------------------------------------------ plans and policy --


def plans() -> dict[str, Any]:
    return call("billing", "GET", "/internal/admin/plans")


def reprice(admin: PlatformAdmin, ip: str, version_id: str, body: RepriceIn) -> dict[str, Any]:
    key = str(_uuid(version_id, _("No such plan version")))
    done = _forward(admin, "POST", f"/internal/admin/plans/{key}/reprice", body.model_dump(mode="json", by_alias=True))
    after = {**done["after"], "reason": body.reason, "scheduled": done.get("scheduled", 0)}
    _action(admin, ip, "plan.repriced", ("plan_version", key), done["before"], after)
    return done


def policy() -> dict[str, Any]:
    return call("billing", "GET", "/internal/admin/policy")


def edit_policy(admin: PlatformAdmin, ip: str, body: PolicyIn) -> dict[str, Any]:
    done = _forward(admin, "PUT", "/internal/admin/policy", body.model_dump(mode="json", by_alias=True))
    _action(
        admin, ip, "policy.edited", ("billing_policy", str(done["after"]["version"])), done["before"], done["after"]
    )
    return done
