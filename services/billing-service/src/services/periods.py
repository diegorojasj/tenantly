"""Billing periods: calendar months in UTC, rolled forward as time passes (docs/BILLING.md §5).

A period that has ended becomes `closing` and takes late usage for the billing policy's grace
(72 hours to start with; the outbox may still be delivering it), then is reconciled and
invoiced. Renewal is where a scheduled downgrade, a new price list or a cancellation takes
effect. Everything here runs with the subscription row locked by the caller, so two requests
can't roll the same subscription twice.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import BillingPeriod, SubscriptionChange, TenantSubscription, UsageRecord
from . import policy

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

DECEMBER = 12
TENANTLY = ("tenantly", "Tenantly")


def now() -> datetime:
    return timezone.now()


def month_start(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(at: datetime) -> datetime:
    start = month_start(at)
    if start.month == DECEMBER:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def segment(version_id: object, since: datetime) -> dict[str, str]:
    return {"version": str(version_id), "from": since.isoformat()}


def open_period(sub: TenantSubscription, starts_at: datetime) -> BillingPeriod:
    return BillingPeriod.objects.create(
        tenant_id=sub.tenant_id,
        subscription=sub,
        starts_at=starts_at,
        ends_at=next_month(starts_at),
        segments=[segment(sub.plan_version_id, starts_at)],
    )


def latest(sub: TenantSubscription) -> BillingPeriod | None:
    return BillingPeriod.objects.filter(subscription=sub).order_by("-starts_at").first()


def current(sub: TenantSubscription) -> BillingPeriod | None:
    return BillingPeriod.objects.filter(subscription=sub, status=BillingPeriod.Status.OPEN).first()


def _record(sub: TenantSubscription, kind: str, at: datetime, **extra: object) -> None:
    SubscriptionChange.objects.create(
        subscription=sub, kind=kind, effective_at=at, actor_id=TENANTLY[0], actor_name=TENANTLY[1], **extra
    )


def end_subscription(sub: TenantSubscription, at: datetime, reason: str) -> None:
    sub.status = TenantSubscription.Status.CANCELED
    sub.canceled_at = at
    sub.retention_until = (at + timedelta(days=policy.current().retention_days)).date()
    sub.cancel_at_period_end = False
    sub.scheduled_plan_version = None
    sub.revision += 1
    sub.save()
    _record(sub, SubscriptionChange.Kind.CANCELED, at, detail={"reason": reason})


def _renew(sub: TenantSubscription, ended: BillingPeriod) -> BillingPeriod | None:
    if sub.cancel_at_period_end:
        end_subscription(sub, ended.ends_at, "requested")
        return None
    if sub.scheduled_plan_version_id:
        old = sub.plan_version
        sub.plan_version = sub.scheduled_plan_version
        sub.scheduled_plan_version = None
        sub.revision += 1
        sub.save()
        # The same plan's new price list (Tenantly repriced it), or a move to a lower tier.
        repriced = old.code == sub.plan_version.code and old.tenant_id is None
        kind = SubscriptionChange.Kind.REPRICE_APPLIED if repriced else SubscriptionChange.Kind.DOWNGRADE_APPLIED
        _record(sub, kind, ended.ends_at, from_version=old, to_version=sub.plan_version)
    return open_period(sub, ended.ends_at)


def roll(sub: TenantSubscription, at: datetime) -> BillingPeriod | None:
    """Bring the open period up to `at`; None when the subscription has ended."""
    period = current(sub)
    while period and period.ends_at <= at:
        period.status = BillingPeriod.Status.CLOSING
        period.save(update_fields=["status"])
        period = _renew(sub, period)
    return period


def end_early(sub: TenantSubscription, at: datetime) -> None:
    """Cut the open period short at `at` (a cancellation for non-payment): billed up to then."""
    period = current(sub)
    if period and at > period.starts_at:
        period.ends_at = at
        period.status = BillingPeriod.Status.CLOSING
        period.save(update_fields=["ends_at", "status"])


def holding(sub: TenantSubscription, at: datetime) -> BillingPeriod | None:
    """The period `at` falls in, after rolling up to now."""
    roll(sub, now())
    return BillingPeriod.objects.filter(subscription=sub, starts_at__lte=at, ends_at__gt=at).first()


# --------------------------------------------------------------- closing --


def reconcile(period: BillingPeriod) -> list[str]:
    """Counters against subjects, subjects against the evidence. Empty when everything agrees."""
    problems: list[str] = []
    for counter in period.counters.all():
        live = period.subjects.filter(metric=counter.metric, sources__gt=0).count()
        if live != counter.quantity:
            problems.append(f"{counter.metric}: counter {counter.quantity} != {live} subjects")
    nets = {
        (r["metric"], r["subject_key"]): r["net"]
        for r in UsageRecord.objects.filter(period=period, late=False)
        .values("metric", "subject_key")
        .annotate(net=Sum("delta"))
    }
    for subject in period.subjects.all():
        net = nets.get((subject.metric, subject.subject_key), 0)
        if net != subject.sources:
            problems.append(f"{subject.metric} {subject.subject_key}: {subject.sources} sources != {net} records")
    return problems


def roll_all(at: datetime) -> int:
    rolled = 0
    for sub_id in TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE).values_list(
        "id", flat=True
    ):
        with transaction.atomic():
            sub = TenantSubscription.objects.select_for_update().get(pk=sub_id)
            before = current(sub)
            after = roll(sub, at)
            rolled += int(before != after)
    return rolled


def close_due(at: datetime, issue: Callable[[BillingPeriod], object]) -> int:
    """Invoice every period whose grace has passed. Rerunning finds nothing left to do."""
    issued = 0
    grace = timedelta(hours=policy.current().usage_grace_hours)
    due = BillingPeriod.objects.filter(status=BillingPeriod.Status.CLOSING, ends_at__lte=at - grace)
    for period_id in due.order_by("ends_at").values_list("id", flat=True):
        with transaction.atomic():
            period = BillingPeriod.objects.select_for_update().get(pk=period_id)
            if period.status != BillingPeriod.Status.CLOSING:
                continue
            problems = reconcile(period)
            if problems:
                # Never invoice numbers that don't add up: staff look first.
                log.error("period %s held: %s", period.id, "; ".join(problems))
                period.status = BillingPeriod.Status.HELD
                period.save(update_fields=["status"])
                continue
            issue(period)
            period.status = BillingPeriod.Status.INVOICED
            period.closed_at = at
            period.save(update_fields=["status", "closed_at"])
            issued += 1
    return issued
