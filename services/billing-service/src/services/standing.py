"""How far behind on payment a business is, derived on read (docs/BILLING.md §5.1).

Day 0 is the oldest unpaid invoice's due date. The days come from the billing policy in force
(services/policy.py; 14, 30 and 45 to start with): until the first nothing changes but reminders
(`past_due`); then no new customers (`limited`); then no new bookings either (`restricted`);
on the last the subscription is canceled by the daily cycle. Extensions shift every date; a
dispute stops the escalation; a balance under the policy's small balance never escalates.
Paying is enough to be `active` again: nothing here is stored, so nothing can go stale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Sum
from django.utils import timezone

from common.money import wire

from ..models import BillingPolicy, EntitlementGrant, PlanInvoice, TenantSubscription
from . import policy

if TYPE_CHECKING:
    from datetime import datetime

ACTIVE, PAST_DUE, LIMITED, RESTRICTED, CANCELED = "active", "past_due", "limited", "restricted", "canceled"


@dataclass
class Standing:
    status: str
    invoice: PlanInvoice | None = None
    overdue_days: int = 0
    shift: int = 0
    disputed: bool = False
    balance: Decimal = Decimal(0)
    rules: BillingPolicy = field(default_factory=policy.current)

    def on(self, after: int) -> date | None:
        return self.invoice.due_on + timedelta(days=after + self.shift) if self.invoice else None

    @property
    def cancels_due(self) -> bool:
        return (
            self.invoice is not None
            and not self.disputed
            and self.overdue_days >= self.rules.cancel_after_days
            and self.balance >= self.rules.small_balance
        )


def _open_invoices(tenant_id: object) -> Any:
    return PlanInvoice.objects.filter(tenant_id=tenant_id, status=PlanInvoice.Status.OPEN)


def of(sub: TenantSubscription, today: date, at: datetime | None = None) -> Standing:
    rules = policy.current()
    if sub.status == TenantSubscription.Status.CANCELED:
        return Standing(CANCELED, rules=rules)
    invoices = _open_invoices(sub.tenant_id)
    oldest = invoices.order_by("due_on", "number").first()
    if not oldest:
        return Standing(ACTIVE, rules=rules)
    balance = invoices.aggregate(s=Sum("total"))["s"] or Decimal(0)
    grants = EntitlementGrant.objects.filter(tenant_id=sub.tenant_id)
    shift = int(
        grants.filter(kind=EntitlementGrant.Kind.EXTEND_GRACE, valid_from__gte=oldest.issued_at).aggregate(
            s=Sum("value")
        )["s"]
        or 0
    )
    moment = at or timezone.now()
    disputed = grants.filter(
        kind=EntitlementGrant.Kind.DISPUTE, valid_from__lte=moment, valid_until__gt=moment
    ).exists()
    late = (today - oldest.due_on).days - shift
    if late <= 0:
        status = ACTIVE
    elif disputed or balance < rules.small_balance or late < rules.limit_after_days:
        status = PAST_DUE
    elif late < rules.restrict_after_days:
        status = LIMITED
    else:
        status = RESTRICTED
    return Standing(status, oldest, max(late, 0), shift, disputed, balance, rules)


def extension_available(sub: TenantSubscription, st: Standing, today: date) -> bool:
    if st.status not in (PAST_DUE, LIMITED, RESTRICTED):
        return False
    return sub.extension_used_on is None or today - sub.extension_used_on >= policy.extension_every(st.rules)


def standing_dict(sub: TenantSubscription, st: Standing, today: date) -> dict[str, Any]:
    inv = st.invoice
    return {
        "status": st.status,
        "invoice": {"id": str(inv.id), "number": inv.code, "dueOn": inv.due_on.isoformat(), "total": wire(inv.total)}
        if inv
        else None,
        "balance": wire(st.balance),
        "overdueDays": st.overdue_days,
        "disputed": st.disputed,
        "limitsOn": d.isoformat() if (d := st.on(st.rules.limit_after_days)) else None,
        "restrictsOn": d.isoformat() if (d := st.on(st.rules.restrict_after_days)) else None,
        "cancelsOn": d.isoformat() if (d := st.on(st.rules.cancel_after_days)) else None,
        "extensionAvailable": extension_available(sub, st, today),
        "retentionUntil": sub.retention_until.isoformat() if sub.retention_until else None,
    }
