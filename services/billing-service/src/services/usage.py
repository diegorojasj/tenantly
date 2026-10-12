"""Usage: recording what operations reports, exactly once, and reading it back (docs/BILLING.md §3, §7.1).

Operations writes each usage event in the same transaction as the business change behind
it and delivers it through its outbox, keyed `ops-<id>`. Here an event is stored as
evidence (`UsageRecord`) and counted on a distinct subject per period (`ActiveSubject`),
all under the subscription's row lock:

- the same key twice, or the same source counted twice under different keys → no-op;
- a customer's second visit in a period → evidence only, the count stays;
- a reversal (a class called off) uncounts a customer only if nothing else keeps them;
- an event for a period already invoiced → evidence, flagged `late`, never billed.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction

from ..models import ActiveSubject, BillingPeriod, UsageCounter, UsageRecord
from . import catalog, notices, periods, pricing, subscriptions

if TYPE_CHECKING:
    from datetime import datetime

    from common.auth import TenantClaims

    from ..models import TenantSubscription
    from ..schemas import UsageIn

PAGE = 100


def _target(sub: TenantSubscription, body: UsageIn) -> tuple[BillingPeriod | None, bool]:
    """The period the event belongs to, and whether it arrived too late to count there."""
    if body.delta < 0:
        original = (
            UsageRecord.objects.filter(tenant_id=sub.tenant_id, metric=body.metric, source_ref=body.source_ref, delta=1)
            .select_related("period")
            .first()
        )
        if not original:
            return periods.latest(sub), True
        return original.period, original.late or not original.period.takes_usage
    period = periods.holding(sub, min(body.occurred_at, periods.now()))
    if not period:
        return periods.latest(sub), True
    return period, not period.takes_usage


@transaction.atomic
def record(body: UsageIn) -> dict[str, bool]:
    if UsageRecord.objects.filter(tenant_id=body.tenant_id, idempotency_key=body.key).exists():
        return {"recorded": False}
    sub = subscriptions.locked(body.tenant_id)
    period, late = _target(sub, body)
    if period is None:
        return {"recorded": False}
    try:
        with transaction.atomic():
            rec = UsageRecord.objects.create(
                tenant_id=body.tenant_id,
                period=period,
                metric=body.metric,
                subject_key=body.subject_key,
                label=body.label,
                source=body.source,
                source_ref=body.source_ref,
                delta=body.delta,
                occurred_at=body.occurred_at,
                late=late,
                idempotency_key=body.key,
            )
    except IntegrityError:
        # This source already counted (or was already reversed) under another key.
        return {"recorded": False}
    if not late:
        _count(sub, period, rec)
    return {"recorded": True}


def _count(sub: TenantSubscription, period: BillingPeriod, rec: UsageRecord) -> None:
    subject, _ = ActiveSubject.objects.select_for_update().get_or_create(
        period=period,
        metric=rec.metric,
        subject_key=rec.subject_key,
        defaults={
            "label": rec.label,
            "first_seen_at": rec.occurred_at,
            "first_source": rec.source,
            "first_ref": rec.source_ref,
        },
    )
    before = subject.sources
    subject.sources = max(0, before + rec.delta)
    if before == 0 and subject.sources > 0:
        subject.first_seen_at, subject.first_source, subject.first_ref = rec.occurred_at, rec.source, rec.source_ref
        subject.label = rec.label or subject.label
    subject.save()
    step = 1 if before == 0 < subject.sources else -1 if subject.sources == 0 < before else 0
    if not step:
        return
    counter, _ = UsageCounter.objects.select_for_update().get_or_create(
        period=period, metric=rec.metric, defaults={"tenant_id": sub.tenant_id}
    )
    old = counter.quantity
    counter.quantity = max(0, old + step)
    if step > 0 and rec.metric == pricing.METRIC:
        _alerts(sub, period, counter, old)
    counter.save()


def _alerts(sub: TenantSubscription, period: BillingPeriod, counter: UsageCounter, old: int) -> None:
    """Thresholds this increment crossed, once each per period; and the cap, once."""
    version = sub.plan_version
    grants = pricing.grants_for(sub.tenant_id, period.starts_at, period.ends_at)
    allowance = pricing.allowance_of(version, grants)
    if not allowance:
        return
    new = counter.quantity
    plan = catalog.plan_dict(version)
    for pct in sub.alert_thresholds:
        mark = math.ceil(allowance * pct / 100)
        if old < mark <= new and pct not in counter.notified:
            counter.notified = [*counter.notified, pct]
            notices.notify(
                sub.tenant_id,
                "threshold",
                f"threshold:{period.id}:{pct}",
                {
                    "percent": pct,
                    "used": new,
                    "allowance": allowance,
                    "plan": plan["name"],
                    "overagePrice": plan["overagePrice"],
                    "cap": plan["cap"],
                    "periodEnd": period.ends_at.isoformat(),
                },
            )
    cap = pricing.cap_of(version, sub.spend_cap)
    unit = version.unit_price(pricing.METRIC)
    over = cap is not None and unit is not None and new > allowance
    if over and version.base_price + unit * (new - allowance) >= cap:  # type: ignore[operator]
        notices.notify(
            sub.tenant_id,
            "cap",
            f"cap:{period.id}",
            {"cap": str(cap), "used": new, "periodEnd": period.ends_at.isoformat()},
        )


# --------------------------------------------------------------- reading --


def used(period: BillingPeriod, metric: str = pricing.METRIC) -> int:
    counter = UsageCounter.objects.filter(period=period, metric=metric).first()
    return counter.quantity if counter else 0


def daily(period: BillingPeriod, until: datetime) -> list[int]:
    """Customers newly counted per day of the period, up to `until`."""
    end = min(until, period.ends_at)
    days = max(1, math.ceil((end - period.starts_at).total_seconds() / 86_400))
    per_day = Counter(
        int((s.first_seen_at - period.starts_at).total_seconds() // 86_400)
        for s in period.subjects.filter(metric=pricing.METRIC, sources__gt=0).only("first_seen_at")
    )
    return [per_day.get(i, 0) for i in range(days)]


def counted(claims: TenantClaims, period_id: int | None, offset: int) -> dict[str, Any]:
    """Who was counted in a period and why: the answer to "where does this number come from?"."""
    claims.demand_any(("billing.view", "billing.manage"))
    rows = BillingPeriod.objects.filter(tenant_id=claims.tenant_id)
    period = rows.filter(id=period_id).first() if period_id else rows.filter(status=BillingPeriod.Status.OPEN).first()
    if not period:
        return {"periodId": None, "total": 0, "customers": []}
    subjects = period.subjects.filter(metric=pricing.METRIC, sources__gt=0)
    return {
        "periodId": period.id,
        "start": period.starts_at.isoformat(),
        "end": period.ends_at.isoformat(),
        "total": subjects.count(),
        "customers": [
            {
                "customerId": s.subject_key,
                "name": s.label,
                "firstSeenAt": s.first_seen_at.isoformat(),
                "source": s.first_source,
                "reference": s.first_ref,
            }
            for s in subjects[offset : offset + PAGE]
        ],
    }
