"""The billing page in one read: plan, period, usage, the running bill and how it's made (docs/BILLING.md §9).

Every number on the page comes from here, so the page never prices anything itself. The
estimate is the same quote the invoice will freeze; each offered plan also says what this
period would cost on it, so "should I upgrade?" has a number for an answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Sum

from common.money import ZERO, wire

from ..models import BillingPeriod, Charge, TenantSubscription
from . import catalog, notices, periods, policy, pricing, standing, statements, stripe, subscriptions, usage

if TYPE_CHECKING:
    from datetime import datetime

    from common.auth import TenantClaims

    from ..models import PlanVersion

VIEW = ("billing.view", "billing.manage")


def _on(version: PlanVersion, period: BillingPeriod, sub: TenantSubscription, used: int) -> str:
    """What this whole period would cost on `version` at this usage."""
    whole = BillingPeriod(
        starts_at=period.starts_at, ends_at=period.ends_at, segments=[periods.segment(version.id, period.starts_at)]
    )
    grants = pricing.grants_for(sub.tenant_id, period.starts_at, period.ends_at)
    return wire(pricing.quote(whole, {str(version.id): version}, used, grants, None).total)


def _informational(claims: TenantClaims, period: BillingPeriod) -> dict[str, Any]:
    """Shown for context, never billed: payments taken and collected in the period."""
    charges = Charge.objects.filter(tenant_id=claims.tenant_id)
    in_period = charges.filter(created_at__gte=period.starts_at, created_at__lt=period.ends_at)
    collected = charges.filter(
        status=Charge.Status.PAID, paid_on__gte=period.starts_at.date(), paid_on__lt=period.ends_at.date()
    ).aggregate(s=Sum("amount"))["s"]
    return {
        "bookings": usage.used(period, "bookings"),
        "payments": in_period.exclude(status=Charge.Status.REFUNDED).count(),
        "collected": {"amount": wire(collected or ZERO), "currency": claims.currency},
    }


def _usage(period: BillingPeriod, used: int, allowance: int | None, at: datetime) -> dict[str, Any]:
    projected = pricing.projected(used, period, at) if period.status == BillingPeriod.Status.OPEN else None
    return {
        "metric": pricing.METRIC,
        "used": used,
        "allowance": allowance,
        "remaining": max(0, allowance - used) if allowance is not None else None,
        "percent": round(used * 100 / allowance) if allowance else None,
        "projected": projected,
        "series": usage.daily(period, at),
    }


def overview(claims: TenantClaims) -> dict[str, Any]:
    claims.demand_any(VIEW)
    at = periods.now()
    today = at.date()
    with transaction.atomic():
        sub = subscriptions.locked(claims.tenant_id)
        period = periods.roll(sub, at) or periods.latest(sub)
    used = usage.used(period)
    q = statements.quote(period, sub, used)
    info = _usage(period, used, q.allowance, at)
    projected = info["projected"]
    version = sub.plan_version
    unit = version.unit_price(pricing.METRIC)
    rules = policy.current()
    return {
        "currency": version.currency,
        "plan": catalog.plan_dict(version),
        "scheduled": catalog.plan_dict(sub.scheduled_plan_version) if sub.scheduled_plan_version else None,
        "status": sub.status,
        "cancelAtPeriodEnd": sub.cancel_at_period_end,
        "standing": standing.standing_dict(sub, standing.of(sub, today, at), today),
        "revision": sub.revision,
        "canManage": subscriptions.can_manage(claims),
        "payment": {
            "method": sub.payment_method,
            "card": bool(sub.stripe_payment_method_id),
            "cardsAvailable": stripe.configured(),
        },
        "alertThresholds": sub.alert_thresholds,
        # The billing policy's numbers the page quotes in its wording.
        "policy": {"paymentTermsDays": rules.payment_terms_days, "extensionDays": rules.extension_days},
        "spendCap": {
            "editable": unit is not None and version.overage_cap is None,
            "value": wire(sub.spend_cap) if sub.spend_cap is not None else None,
            "default": wire(pricing.default_spend_cap(version)),
        },
        "period": {
            "id": period.id,
            "start": period.starts_at.isoformat(),
            "end": period.ends_at.isoformat(),
            "status": period.status,
        },
        "usage": info,
        "estimate": {
            "lines": [line.wire() for line in q.lines],
            "total": wire(q.total),
            "cap": wire(q.cap) if q.cap is not None else None,
            "projectedTotal": wire(statements.quote(period, sub, projected).total)
            if projected is not None and projected > used
            else None,
        },
        "informational": _informational(claims, period),
        "plans": [{**catalog.plan_dict(v), "thisPeriod": _on(v, period, sub, used)} for v in catalog.offered()],
        "notices": notices.recent(sub.tenant_id),
    }


def entitlements(tenant_id: str) -> dict[str, Any]:
    """What identity puts in the tenant token: the plan's name and the payment standing.

    Never creates the subscription: identity asks this while issuing a token, and creating
    it would call identity back mid-request. It's created on the billing page or with the
    first usage instead; until then the business is simply in good standing.
    """
    sub = TenantSubscription.objects.select_related("plan_version").filter(tenant_id=tenant_id).first()
    if not sub:
        return {"plan": None, "status": standing.ACTIVE}
    today = periods.now().date()
    return {"plan": sub.plan_version.name, "status": standing.of(sub, today).status}
