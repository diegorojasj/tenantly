"""A business's Tenantly subscription: created on first use, changed by its owner or by Tenantly.

Rules (docs/BILLING.md §5): an upgrade takes effect now and prorates; a downgrade waits for
the renewal and can be withdrawn; cancelling takes effect at the period's end and can be
undone until then. Every change is a `SubscriptionChange` row and an audit entry, keyed so
that a retried request never applies twice, and checked against the subscription's
revision so two people can't overwrite each other.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from common.errors import ConflictError, ForbiddenError, InvalidError
from common.internal import audit, call

from ..models import EntitlementGrant, PlanInvoice, SubscriptionChange, TenantSubscription
from . import catalog, periods, policy, pricing, standing, trail

if TYPE_CHECKING:
    from common.auth import TenantClaims

    from ..models import PlanVersion
    from ..schemas import PlanAssignIn, PlanSettingsIn

MANAGE = "billing.manage"
OWNER = "owner"
LEGACY_NAMES = {"Starter": "starter", "Growth": "growth", "Enterprise": "enterprise"}
MAX_THRESHOLD = 100


# --------------------------------------------------------------- creating --


def _imported(tenant_id: str) -> tuple[PlanVersion, datetime]:
    """What identity held before billing owned the plan: the tier (or Custom terms) and since when."""
    held = call("identity", "GET", f"/internal/tenants/{tenant_id}/plan")
    since = datetime.fromisoformat(held["since"]) if held.get("since") else periods.now()
    terms = held.get("terms") or {}
    if held.get("plan") == "Custom" and terms.get("price") is not None:
        version = catalog.custom(tenant_id, Decimal(str(terms["price"])), terms.get("customerLimit"), None, since)
        return version, since
    return catalog.in_force(LEGACY_NAMES.get(held.get("plan", ""), "starter"), since), since


def ensure(tenant_id: str) -> TenantSubscription:
    """The business's subscription, created (from what identity held) the first time it's needed."""
    sub = TenantSubscription.objects.filter(tenant_id=tenant_id).first()
    if sub:
        return sub
    try:
        with transaction.atomic():
            version, since = _imported(tenant_id)
            sub = TenantSubscription.objects.create(
                tenant_id=tenant_id, plan_version=version, alert_thresholds=policy.current().alert_thresholds
            )
            start = max(since, periods.month_start(periods.now()))
            periods.open_period(sub, start)
            SubscriptionChange.objects.create(
                subscription=sub,
                kind=SubscriptionChange.Kind.CREATED,
                to_version=version,
                effective_at=start,
                actor_id=periods.TENANTLY[0],
                actor_name=periods.TENANTLY[1],
            )
    except IntegrityError:
        # Created by a concurrent request in the meantime.
        return TenantSubscription.objects.get(tenant_id=tenant_id)
    return sub


def locked(tenant_id: str) -> TenantSubscription:
    """The subscription, row-locked for the rest of the caller's transaction."""
    sub = ensure(tenant_id)
    return TenantSubscription.objects.select_for_update().select_related("plan_version").get(pk=sub.pk)


def _change(sub: TenantSubscription, kind: str, actor: tuple[str, str], key: str | None, **extra: Any) -> None:
    sub.revision += 1
    sub.save()
    SubscriptionChange.objects.create(
        subscription=sub,
        kind=kind,
        effective_at=periods.now(),
        actor_id=actor[0],
        actor_name=actor[1],
        idempotency_key=key or None,
        **extra,
    )


def demand_owner(claims: TenantClaims) -> None:
    """The subscription is the owner's: their team works under it and never changes it.

    Checked on the role as well as the permission, so a role edited to carry `billing.manage`
    (or a token from before it became owner-only) still can't.
    """
    claims.demand(MANAGE)
    if claims.role != OWNER:
        msg = _("Only the business's owner can change its Tenantly plan")
        raise ForbiddenError(msg)


def can_manage(claims: TenantClaims) -> bool:
    return claims.role == OWNER and claims.can(MANAGE)


def _actor(claims: TenantClaims) -> tuple[str, str]:
    return claims.user_id, claims.user_name


def _guard(claims: TenantClaims, sub: TenantSubscription, revision: int | None, key: str | None) -> bool:
    """True when this request was already applied (same key); raises on a stale revision."""
    demand_owner(claims)
    if key and sub.changes.filter(idempotency_key=key).exists():
        return True
    if revision is not None and revision != sub.revision:
        msg = _("Someone changed the plan in the meantime: look again before changing it")
        raise ConflictError(msg)
    return False


def _live(sub: TenantSubscription) -> None:
    if sub.status == TenantSubscription.Status.CANCELED:
        msg = _("This subscription has ended: reactivate it first")
        raise InvalidError(msg)


# ------------------------------------------------------ the business acts --


@transaction.atomic
def change_plan(claims: TenantClaims, code: str, revision: int, key: str | None) -> None:
    sub = locked(claims.tenant_id)
    if _guard(claims, sub, revision, key):
        return
    _live(sub)
    if sub.cancel_at_period_end:
        # Otherwise an upgrade would be billed now and the plan would still end at renewal.
        msg = _("The plan ends with this period: resume it before changing plans")
        raise InvalidError(msg)
    target = catalog.public(code)
    current = sub.plan_version
    if target.id == current.id:
        if not sub.scheduled_plan_version_id:
            msg = _("You're already on this plan")
            raise InvalidError(msg)
        _withdraw(claims, sub, key)
        return
    if target.rank > current.rank:
        period = periods.roll(sub, periods.now())
        if period:
            period.segments = [*period.segments, periods.segment(target.id, periods.now())]
            period.save(update_fields=["segments"])
        sub.plan_version = target
        sub.scheduled_plan_version = None
        _change(sub, SubscriptionChange.Kind.UPGRADE, _actor(claims), key, from_version=current, to_version=target)
        audit(claims, "tenantly.plan_upgraded", "billing", f"{current.name} → {target.name}", None)
        return
    # Lower tier, or the same tier's newer price list: from the next renewal.
    sub.scheduled_plan_version = target
    _change(
        sub, SubscriptionChange.Kind.DOWNGRADE_SCHEDULED, _actor(claims), key, from_version=current, to_version=target
    )
    audit(claims, "tenantly.downgrade_scheduled", "billing", f"{current.name} → {target.name}", None)


def _withdraw(claims: TenantClaims, sub: TenantSubscription, key: str | None) -> None:
    current, withdrawn = sub.plan_version, sub.scheduled_plan_version
    sub.scheduled_plan_version = None
    _change(
        sub,
        SubscriptionChange.Kind.DOWNGRADE_WITHDRAWN,
        _actor(claims),
        key,
        from_version=current,
        to_version=withdrawn,
    )
    audit(claims, "tenantly.downgrade_withdrawn", "billing", f"{withdrawn.name} → {current.name}", None)


@transaction.atomic
def withdraw(claims: TenantClaims, revision: int, key: str | None) -> None:
    """Keep the current plan after all: drop the change waiting for the renewal.

    Its own action, since the current plan may be a Custom plan or an older price list that
    `change_plan` can't name (it only offers the current public ones).
    """
    sub = locked(claims.tenant_id)
    if _guard(claims, sub, revision, key):
        return
    if not sub.scheduled_plan_version_id:
        msg = _("No plan change is waiting for the renewal")
        raise InvalidError(msg)
    _withdraw(claims, sub, key)


@transaction.atomic
def cancel(claims: TenantClaims, revision: int, key: str | None) -> None:
    sub = locked(claims.tenant_id)
    if _guard(claims, sub, revision, key):
        return
    _live(sub)
    if sub.cancel_at_period_end:
        msg = _("The plan already ends with this period")
        raise InvalidError(msg)
    sub.cancel_at_period_end = True
    sub.scheduled_plan_version = None
    _change(sub, SubscriptionChange.Kind.CANCEL_SCHEDULED, _actor(claims), key)
    audit(claims, "tenantly.cancel_scheduled", "billing", sub.plan_version.name, None)


@transaction.atomic
def resume(claims: TenantClaims, revision: int, key: str | None) -> None:
    """Undo a cancellation that hasn't happened yet, or reactivate an ended subscription."""
    sub = locked(claims.tenant_id)
    if _guard(claims, sub, revision, key):
        return
    if sub.cancel_at_period_end:
        sub.cancel_at_period_end = False
        _change(sub, SubscriptionChange.Kind.CANCEL_WITHDRAWN, _actor(claims), key)
        audit(claims, "tenantly.cancel_withdrawn", "billing", sub.plan_version.name, None)
        return
    if sub.status != TenantSubscription.Status.CANCELED:
        msg = _("The plan isn't ending")
        raise InvalidError(msg)
    if PlanInvoice.objects.filter(tenant_id=sub.tenant_id, status=PlanInvoice.Status.OPEN).exists():
        msg = _("Pay the open Tenantly invoices first: that reactivates the plan")
        raise InvalidError(msg)
    reactivate(sub, _actor(claims), key)
    audit(claims, "tenantly.reactivated", "billing", sub.plan_version.name, None)


def reactivate(sub: TenantSubscription, actor: tuple[str, str], key: str | None = None) -> None:
    """Back to active from now, on the same plan (or its current price list if that one's retired)."""
    sub.status = TenantSubscription.Status.ACTIVE
    sub.canceled_at = None
    sub.retention_until = None
    if sub.plan_version.status != sub.plan_version.Status.ACTIVE and sub.plan_version.tenant_id is None:
        sub.plan_version = catalog.public(sub.plan_version.code)
    periods.open_period(sub, periods.now())
    _change(sub, SubscriptionChange.Kind.REACTIVATED, actor, key, to_version=sub.plan_version)


@transaction.atomic
def update_settings(claims: TenantClaims, body: PlanSettingsIn) -> None:
    demand_owner(claims)
    sub = locked(claims.tenant_id)
    thresholds = sorted(set(body.alert_thresholds))
    if any(t < 1 or t > MAX_THRESHOLD for t in thresholds):
        msg = _("Alerts go from 1% to 100% of the allowance")
        raise InvalidError(msg)
    if body.spend_cap is not None:
        if pricing.cap_of(sub.plan_version, None) is None or sub.plan_version.overage_cap is not None:
            msg = _("Your plan already caps every period at the next plan's price")
            raise InvalidError(msg)
        if body.spend_cap < sub.plan_version.base_price:
            msg = _("The spend cap can't be below the plan's price")
            raise InvalidError(msg)
    sub.spend_cap = body.spend_cap
    sub.alert_thresholds = thresholds
    detail = {"spendCap": str(body.spend_cap) if body.spend_cap is not None else None, "alerts": thresholds}
    _change(sub, SubscriptionChange.Kind.SETTINGS, _actor(claims), None, detail=detail)
    audit(claims, "tenantly.plan_settings", "billing", ", ".join(f"{t}%" for t in thresholds), None)


@transaction.atomic
def extend(claims: TenantClaims, key: str | None) -> None:
    """More days before an unpaid invoice escalates (7, once every 12 months, per the billing policy)."""
    sub = locked(claims.tenant_id)
    if _guard(claims, sub, None, key):
        return
    today = periods.now().date()
    st = standing.of(sub, today)
    if not standing.extension_available(sub, st, today):
        msg = _("No extension is available right now")
        raise InvalidError(msg)
    at = periods.now()
    rules = st.rules
    EntitlementGrant.objects.create(
        tenant_id=sub.tenant_id,
        kind=EntitlementGrant.Kind.EXTEND_GRACE,
        value=rules.extension_days,
        valid_from=at,
        valid_until=at + policy.extension_every(rules),
        reason="Self-serve payment extension",
        approved_by=claims.user_name,
    )
    sub.extension_used_on = today
    _change(sub, SubscriptionChange.Kind.EXTENSION, _actor(claims), key, detail={"days": rules.extension_days})
    audit(claims, "tenantly.payment_extended", "billing", st.invoice.code if st.invoice else "", None)


# ------------------------------------------------------- Tenantly acts --


def _subscribe(tenant_id: str, version: PlanVersion, actor: tuple[str, str], reason: str) -> TenantSubscription:
    """A first subscription Tenantly sets up itself: on the plan it assigns, billed from now.

    Unlike `ensure`, nothing is imported from identity, which may be the caller (the admin
    console): what it held is moot once Tenantly picks the plan.
    """
    at = periods.now()
    sub = TenantSubscription.objects.create(
        tenant_id=tenant_id, plan_version=version, alert_thresholds=policy.current().alert_thresholds
    )
    periods.open_period(sub, at)
    SubscriptionChange.objects.create(
        subscription=sub,
        kind=SubscriptionChange.Kind.CREATED,
        to_version=version,
        effective_at=at,
        actor_id=actor[0],
        actor_name=actor[1],
        detail={"reason": reason} if reason else {},
    )
    return sub


def _target(tenant_id: str, body: PlanAssignIn, at: datetime) -> PlanVersion:
    if (body.plan == catalog.CUSTOM) != bool(body.terms):
        msg = _("A Custom plan needs its terms, and only a Custom plan takes them")
        raise InvalidError(msg)
    if body.terms:
        return catalog.custom(tenant_id, body.terms.price, body.terms.customer_limit, body.terms.overage_price, at)
    return catalog.public(body.plan)


def snapshot(tenant_id: str) -> dict[str, Any] | None:
    """The subscription as it stands, for an audit log's "before"; None when there's none yet."""
    sub = TenantSubscription.objects.select_related("plan_version").filter(tenant_id=tenant_id).first()
    if not sub:
        return None
    return {"plan": sub.plan_version.name, "version": sub.plan_version.version, "status": sub.status}


@transaction.atomic
def assign(tenant_id: str, body: PlanAssignIn) -> TenantSubscription:
    """Tenantly moves a business to a plan now, e.g. the Custom plan agreed with its owner."""
    actor = (body.actor.id, body.actor.name) if body.actor else periods.TENANTLY
    at = periods.now()
    rows = TenantSubscription.objects.select_for_update().select_related("plan_version")
    sub = rows.filter(tenant_id=tenant_id).first()
    target = _target(tenant_id, body, at)
    if not sub:
        sub = _subscribe(tenant_id, target, actor, body.reason)
        trail.tenantly(tenant_id, "tenantly.plan_assigned", target.name, actor)
        return sub
    old = sub.plan_version
    if sub.status == TenantSubscription.Status.CANCELED:
        sub.plan_version = target
        reactivate(sub, actor)
    else:
        period = periods.roll(sub, at)
        if period:
            period.segments = [*period.segments, periods.segment(target.id, at)]
            period.save(update_fields=["segments"])
        sub.plan_version = target
        sub.scheduled_plan_version = None
        _change(
            sub,
            SubscriptionChange.Kind.ASSIGNED,
            actor,
            None,
            from_version=old,
            to_version=target,
            detail={"reason": body.reason},
        )
    trail.tenantly(tenant_id, "tenantly.plan_assigned", f"{old.name} → {target.name}", actor)
    return sub
