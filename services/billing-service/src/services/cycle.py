"""The daily billing cycle (`manage.py billing_cycle`): renew, invoice, charge, chase.

Every step is idempotent, so running it twice, or again after a crash halfway, does
nothing new. Collections follow docs/BILLING.md §5.1: one notice per milestone reached
(the highest one, so a missed day doesn't send a burst), card retries on days 3 and 7,
and cancellation on day 45 unless the invoice is disputed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction

from ..models import PlanInvoice, TenantSubscription
from . import notices, periods, standing, statements, stripe, trail

if TYPE_CHECKING:
    from datetime import date, datetime

    from ..models import BillingPolicy

log = logging.getLogger(__name__)

REMINDERS = (1, 3, 7)
# How many days ahead of each step the warning goes out (day 11, 25 and 40 under the first policy).
WARN_BEFORE_LIMIT = 3
WARN_BEFORE_RESTRICT = 5
WARN_BEFORE_CANCEL = 5
CARD_RETRY_DAYS = (3, 7)


def milestones(rules: BillingPolicy) -> list[tuple[int, str]]:
    """Day overdue -> notice kind, in order, from the billing policy in force."""
    steps = [
        *((day, "overdue") for day in REMINDERS),
        (rules.limit_after_days - WARN_BEFORE_LIMIT, "limit_warning"),
        (rules.limit_after_days, "limited"),
        (rules.restrict_after_days - WARN_BEFORE_RESTRICT, "restrict_warning"),
        (rules.restrict_after_days, "restricted"),
        (rules.cancel_after_days - WARN_BEFORE_CANCEL, "cancel_warning"),
    ]
    return sorted(steps, key=lambda step: step[0])


def charge_new(at: datetime) -> int:
    """First card attempt for invoices issued to businesses that pay by card."""
    paid = 0
    for invoice in PlanInvoice.objects.filter(status=PlanInvoice.Status.OPEN, attempts=0, issued_at__lte=at):
        paid += int(stripe.charge(invoice))
    return paid


def _chase_one(sub: TenantSubscription, today: date) -> None:
    st = standing.of(sub, today)
    if not st.invoice or st.status == standing.ACTIVE:
        return
    reached = [(day, kind) for day, kind in milestones(st.rules) if st.overdue_days >= day]
    if reached and not st.disputed:
        day, kind = reached[-1]
        notices.notify(
            sub.tenant_id,
            kind,
            f"{kind}:{st.invoice.id}:{day}",
            {
                "number": st.invoice.code,
                "balance": str(st.balance),
                "limitsOn": str(st.on(st.rules.limit_after_days)),
                "restrictsOn": str(st.on(st.rules.restrict_after_days)),
                "cancelsOn": str(st.on(st.rules.cancel_after_days)),
            },
        )
    if st.overdue_days in CARD_RETRY_DAYS and st.invoice.last_attempt_on != today:
        stripe.charge(st.invoice)
    if st.cancels_due:
        with transaction.atomic():
            locked = TenantSubscription.objects.select_for_update().get(pk=sub.pk)
            if locked.status != TenantSubscription.Status.ACTIVE:
                return
            at = periods.now()
            periods.end_early(locked, at)
            periods.end_subscription(locked, at, "nonpayment")
            trail.tenantly(sub.tenant_id, "tenantly.canceled_nonpayment", st.invoice.code)
            notices.notify(
                sub.tenant_id,
                "canceled",
                f"canceled:{st.invoice.id}",
                {"number": st.invoice.code, "retentionUntil": str(locked.retention_until)},
            )


def chase(today: date) -> int:
    owing = PlanInvoice.objects.filter(status=PlanInvoice.Status.OPEN, due_on__lte=today).values("tenant_id")
    subs = TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE, tenant_id__in=owing)
    count = 0
    for sub in subs:
        try:
            _chase_one(sub, today)
            count += 1
        except Exception:
            # One business's trouble never stops the cycle for the others.
            log.exception("chasing %s failed", sub.tenant_id)
    return count


def run(at: datetime | None = None) -> dict[str, Any]:
    at = at or periods.now()
    return {
        "rolled": periods.roll_all(at),
        "invoiced": periods.close_due(at, statements.issue),
        "charged": charge_new(at),
        "chased": chase(at.date()),
    }
