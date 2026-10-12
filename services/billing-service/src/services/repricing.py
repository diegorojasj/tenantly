"""Tenantly changes a public plan's price list (docs/BILLING.md §12, admin console).

A `PlanVersion` is never edited: the change is published as the plan's next version, the
old one stops being offered (`legacy`), and every business on it is scheduled onto the new
one at its next renewal and told so with a notice naming the new price. Until then they
keep paying the old price, and invoices already issued never change.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.money import wire

from ..models import BillingPeriod, PlanVersion, SubscriptionChange, TenantSubscription
from . import catalog, notices, periods, pricing, usage

if TYPE_CHECKING:
    from ..schemas import RepriceIn

METRIC = pricing.METRIC


def _terms(body: RepriceIn) -> dict[str, Any]:
    if body.overage_price is not None and body.included is None:
        msg = _("Overage needs an allowance to start from")
        raise InvalidError(msg)
    if body.cap is not None and body.cap < body.price:
        msg = _("The cap can't be below the plan's price")
        raise InvalidError(msg)
    if not body.reason.strip():
        msg = _("Say why: the reason is kept with the price change")
        raise InvalidError(msg)
    return {
        "base_price": body.price,
        "included": {METRIC: body.included} if body.included is not None else {},
        "overage_price": {METRIC: str(body.overage_price)} if body.overage_price is not None else {},
        "overage_cap": body.cap,
    }


def _same(old: PlanVersion, terms: dict[str, Any]) -> bool:
    return (
        old.base_price == terms["base_price"]
        and old.allowance(METRIC) == terms["included"].get(METRIC)
        and old.unit_price(METRIC) == (Decimal(terms["overage_price"][METRIC]) if terms["overage_price"] else None)
        and old.overage_cap == terms["overage_cap"]
    )


def _notify(sub: TenantSubscription, old: PlanVersion, new: PlanVersion) -> None:
    period = periods.current(sub)
    unit = new.unit_price(METRIC)
    notices.notify(
        sub.tenant_id,
        "plan_repriced",
        f"repriced:{new.id}",
        {
            "plan": new.name,
            "currency": new.currency,
            "oldPrice": wire(old.base_price),
            "price": wire(new.base_price),
            "included": new.allowance(METRIC),
            "overagePrice": wire(unit) if unit is not None else None,
            "cap": wire(new.overage_cap) if new.overage_cap is not None else None,
            "effectiveOn": period.ends_at.date().isoformat() if period else None,
        },
    )


@transaction.atomic
def reprice(version_id: str, body: RepriceIn, actor: tuple[str, str]) -> dict[str, Any]:
    missing = _("No such public plan version")
    try:
        key = uuid.UUID(str(version_id))
    except ValueError as e:
        raise NotFoundError(missing) from e
    old = PlanVersion.objects.select_for_update().filter(id=key).first()
    if not old or old.tenant_id is not None:
        raise NotFoundError(missing)
    if old.status != PlanVersion.Status.ACTIVE:
        msg = _("Only the price list on sale can be changed")
        raise InvalidError(msg)
    terms = _terms(body)
    if _same(old, terms):
        msg = _("Nothing changed: the plan is already priced like this")
        raise InvalidError(msg)
    at = periods.now()
    last = PlanVersion.objects.filter(code=old.code).aggregate(n=Max("version"))["n"] or old.version
    new = PlanVersion.objects.create(
        code=old.code,
        version=last + 1,
        name=old.name,
        currency=old.currency,
        rank=old.rank,
        status=PlanVersion.Status.ACTIVE,
        effective_from=at,
        **terms,
    )
    old.status = PlanVersion.Status.LEGACY
    old.save(update_fields=["status"])
    scheduled = 0
    # Businesses on the old list, and those about to move onto it, go to the new one at renewal.
    subs = TenantSubscription.objects.select_for_update().filter(
        Q(plan_version=old) | Q(scheduled_plan_version=old), status=TenantSubscription.Status.ACTIVE
    )
    for sub in subs.select_related("plan_version"):
        # Leaving, or already moving to another tier: their own choice stands.
        if sub.cancel_at_period_end or (sub.scheduled_plan_version_id not in (None, old.id)):
            continue
        sub.scheduled_plan_version = new
        sub.revision += 1
        sub.save()
        SubscriptionChange.objects.create(
            subscription=sub,
            kind=SubscriptionChange.Kind.REPRICE_SCHEDULED,
            from_version=old,
            to_version=new,
            effective_at=at,
            actor_id=actor[0],
            actor_name=actor[1],
            detail={"reason": body.reason.strip()},
        )
        _notify(sub, old, new)
        scheduled += 1
    return {"before": catalog.plan_dict(old), "after": catalog.plan_dict(new), "scheduled": scheduled}


def _usage(version_ids: list[Any]) -> dict[Any, dict[str, int]]:
    """Active customers this period, summed per version, and how many businesses are past their allowance."""
    out: dict[Any, dict[str, int]] = {v: {"used": 0, "over": 0} for v in version_ids}
    open_periods = BillingPeriod.objects.filter(
        status=BillingPeriod.Status.OPEN,
        subscription__plan_version_id__in=version_ids,
        subscription__status=TenantSubscription.Status.ACTIVE,
    ).select_related("subscription__plan_version")
    for period in open_periods:
        version = period.subscription.plan_version
        used = usage.used(period)
        allowance = version.allowance(METRIC)
        out[version.id]["used"] += used
        out[version.id]["over"] += int(allowance is not None and used > allowance)
    return out


def listing() -> dict[str, Any]:
    """Every public version (on sale and legacy) with its subscribers and this period's usage."""
    versions = list(PlanVersion.objects.filter(tenant_id__isnull=True).order_by("rank", "-version"))
    ids = [v.id for v in versions]
    active = TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE)
    on = dict(
        active.filter(plan_version_id__in=ids)
        .values("plan_version_id")
        .annotate(n=Count("id"))
        .values_list("plan_version_id", "n")
    )
    moving = dict(
        active.filter(scheduled_plan_version_id__in=ids)
        .values("scheduled_plan_version_id")
        .annotate(n=Count("id"))
        .values_list("scheduled_plan_version_id", "n")
    )
    used = _usage(ids)
    custom = active.filter(plan_version__tenant_id__isnull=False).count()
    return {
        "plans": [
            {
                **catalog.plan_dict(v),
                "status": v.status,
                "effectiveFrom": v.effective_from.isoformat(),
                "subscribers": on.get(v.id, 0),
                "scheduledIn": moving.get(v.id, 0),
                "usage": used[v.id],
            }
            for v in versions
        ],
        "customSubscribers": custom,
    }
