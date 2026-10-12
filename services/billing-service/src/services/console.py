"""What the Tenantly admin console reads (identity's `/admin`, through `/internal`).

Nothing here creates a subscription or calls identity: identity asks these while serving
its own request, so a call back would be a cycle. A business with no subscription yet has
no summary and no detail.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from common.errors import NotFoundError
from common.money import ZERO, wire

from ..models import BillingPeriod, EntitlementGrant, PlanInvoice, TenantSubscription
from . import catalog, grants, periods, pricing, standing, statements, usage

if TYPE_CHECKING:
    from datetime import datetime

    from ..schemas import ActorIn, GrantIn, InvoicePaidIn

CHANGES = 20
INVOICES = 12


def _balances(tenant_ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    rows = (
        PlanInvoice.objects.filter(tenant_id__in=tenant_ids, status=PlanInvoice.Status.OPEN)
        .values("tenant_id")
        .annotate(s=Sum("total"))
    )
    return {r["tenant_id"]: r["s"] for r in rows}


def _allowance(period: BillingPeriod | None, sub: TenantSubscription) -> int | None:
    if not period:
        return sub.plan_version.allowance(pricing.METRIC)
    grants_now = pricing.grants_for(sub.tenant_id, period.starts_at, period.ends_at)
    return pricing.allowance_of(sub.plan_version, grants_now)


def summaries(tenant_ids: list[uuid.UUID]) -> dict[str, dict[str, Any]]:
    """One line per business that has a subscription; read-only, so nothing is rolled forward."""
    subs = TenantSubscription.objects.filter(tenant_id__in=tenant_ids).select_related("plan_version")
    owed = _balances(tenant_ids)
    today = periods.now().date()
    out: dict[str, dict[str, Any]] = {}
    for sub in subs:
        period = periods.current(sub) or periods.latest(sub)
        version = sub.plan_version
        out[str(sub.tenant_id)] = {
            "plan": version.name,
            "currency": version.currency,
            "price": wire(version.base_price),
            "status": standing.of(sub, today).status,
            "used": usage.used(period) if period else 0,
            "allowance": _allowance(period, sub),
            "periodEnd": period.ends_at.isoformat() if period else None,
            "openBalance": wire(owed.get(sub.tenant_id) or ZERO),
        }
    return out


def signer(actor: ActorIn | None) -> tuple[str, str]:
    """Who a change is signed by: the admin who acted, else Tenantly (staff tools)."""
    return (actor.id, actor.name) if actor else periods.TENANTLY


def _uuid(value: str, missing: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as e:
        raise NotFoundError(missing) from e


def _subscription(tenant_id: str) -> TenantSubscription:
    missing = _("This business has no Tenantly subscription yet")
    sub = TenantSubscription.objects.filter(tenant_id=_uuid(tenant_id, missing)).first()
    if not sub:
        raise NotFoundError(missing)
    return sub


def _estimate(period: BillingPeriod, sub: TenantSubscription, used: int, at: datetime) -> dict[str, Any]:
    q = statements.quote(period, sub, used)
    projected = pricing.projected(used, period, at) if period.status == BillingPeriod.Status.OPEN else None
    return {
        "usage": {"used": used, "allowance": q.allowance, "projected": projected},
        "estimate": {
            "lines": [line.wire() for line in q.lines],
            "total": wire(q.total),
            "cap": wire(q.cap) if q.cap is not None else None,
            "projectedTotal": wire(statements.quote(period, sub, projected).total)
            if projected is not None and projected > used
            else None,
        },
    }


def detail(tenant_id: str) -> dict[str, Any]:
    """Everything the console's subscription panel shows for one business."""
    at = periods.now()
    today = at.date()
    with transaction.atomic():
        sub = (
            TenantSubscription.objects.select_for_update()
            .select_related("plan_version")
            .get(pk=_subscription(tenant_id).pk)
        )
        period = periods.roll(sub, at) or periods.latest(sub)
    if period:
        reading = _estimate(period, sub, usage.used(period), at)
    else:
        reading = {"usage": {"used": 0, "allowance": _allowance(None, sub), "projected": None}, "estimate": None}
    invoices = PlanInvoice.objects.filter(tenant_id=sub.tenant_id).select_related("period")
    live = EntitlementGrant.objects.filter(tenant_id=sub.tenant_id, valid_until__gt=at).order_by("valid_until")
    changes = sub.changes.select_related("from_version", "to_version")[:CHANGES]
    return {
        "tenantId": str(sub.tenant_id),
        "currency": sub.plan_version.currency,
        "plan": catalog.plan_dict(sub.plan_version),
        "scheduled": catalog.plan_dict(sub.scheduled_plan_version) if sub.scheduled_plan_version else None,
        "status": sub.status,
        "cancelAtPeriodEnd": sub.cancel_at_period_end,
        "standing": standing.standing_dict(sub, standing.of(sub, today, at), today),
        "revision": sub.revision,
        "paymentMethod": sub.payment_method,
        "period": {"start": period.starts_at.isoformat(), "end": period.ends_at.isoformat(), "status": period.status}
        if period
        else None,
        **reading,
        # Every unpaid one, then the most recent others.
        "invoices": [
            statements.invoice_dict(i)
            for i in [
                *invoices.filter(status=PlanInvoice.Status.OPEN),
                *invoices.exclude(status=PlanInvoice.Status.OPEN)[:INVOICES],
            ]
        ],
        "grants": [grants.grant_dict(g) for g in live],
        "changes": [
            {
                "kind": c.kind,
                "from": c.from_version.name if c.from_version else None,
                "to": c.to_version.name if c.to_version else None,
                "at": c.effective_at.isoformat(),
                "by": c.actor_name,
                "detail": c.detail,
            }
            for c in changes
        ],
        "plans": [catalog.plan_dict(v) for v in catalog.offered()],
    }


def invoice_paid(invoice_id: str, body: InvoicePaidIn) -> dict[str, Any]:
    """Staff record a payment made outside the card (a transfer); paying twice changes nothing.

    `before` is the invoice's status beforehand, for the admin audit log.
    """
    key = _uuid(invoice_id, _("No such Tenantly invoice"))
    prior = PlanInvoice.objects.filter(id=key).values_list("status", flat=True).first()
    invoice = statements.mark_paid(key, "manual", body.reference, actor=signer(body.actor))
    paid = statements.invoice_dict(PlanInvoice.objects.select_related("period").get(pk=invoice.pk))
    return {**paid, "before": {"status": prior}}


def add_grant(tenant_id: str, body: GrantIn) -> dict[str, Any]:
    created = grants.grant(
        _subscription(tenant_id).tenant_id,
        body.kind,
        metric=body.metric,
        value=body.value,
        days=body.days,
        reason=body.reason,
        actor=signer(body.actor),
    )
    return grants.grant_dict(created)
