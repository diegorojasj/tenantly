"""The billing policy in force: collections milestones, payment terms, retention, caps (docs/BILLING.md §5.1).

The numbers live in versioned `BillingPolicy` rows, not in code: Tenantly admins edit them
from the console (a new row each time, with who and why) and every rule reads `current()`.
Edits are validated so the escalation always runs forward (limited < restricted < canceled).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils.translation import gettext as _

from common.errors import ConflictError, InvalidError
from common.money import wire

from ..models import BillingPolicy
from . import periods

if TYPE_CHECKING:
    from ..schemas import PolicyIn

HISTORY = 20
MAX_DAYS = 365
MAX_TERMS = 90
MAX_EXTENSION = 30
MAX_RETENTION = 3650
MAX_GRACE_HOURS = 14 * 24
MAX_MULTIPLE = Decimal(10)
MAX_PERCENT = 100

# Used only if the table is somehow empty: the values migration 0006 seeds.
FALLBACK = BillingPolicy(
    version=0,
    limit_after_days=14,
    restrict_after_days=30,
    cancel_after_days=45,
    payment_terms_days=14,
    small_balance=Decimal("5.00"),
    extension_days=7,
    extension_every_days=365,
    retention_days=90,
    usage_grace_hours=72,
    spend_cap_multiple=Decimal("2.00"),
    alert_thresholds=[80, 100],
    edited_by_id="tenantly",
    edited_by="Tenantly",
    reason="",
)


def current() -> BillingPolicy:
    """The newest version in effect now. One indexed read; cheap enough to ask per decision."""
    found = BillingPolicy.objects.filter(effective_at__lte=periods.now()).order_by("-version").first()
    return found or BillingPolicy.objects.order_by("version").first() or FALLBACK


def extension_every(p: BillingPolicy) -> timedelta:
    return timedelta(days=p.extension_every_days)


def policy_dict(p: BillingPolicy) -> dict[str, Any]:
    return {
        "version": p.version,
        "limitAfterDays": p.limit_after_days,
        "restrictAfterDays": p.restrict_after_days,
        "cancelAfterDays": p.cancel_after_days,
        "paymentTermsDays": p.payment_terms_days,
        "smallBalance": wire(p.small_balance),
        "extensionDays": p.extension_days,
        "extensionEveryDays": p.extension_every_days,
        "retentionDays": p.retention_days,
        "usageGraceHours": p.usage_grace_hours,
        "spendCapMultiple": wire(p.spend_cap_multiple),
        "alertThresholds": list(p.alert_thresholds),
        "effectiveAt": p.effective_at.isoformat() if p.effective_at else None,
        "editedBy": p.edited_by,
        "reason": p.reason,
    }


def overview() -> dict[str, Any]:
    return {
        "current": policy_dict(current()),
        "history": [policy_dict(p) for p in BillingPolicy.objects.order_by("-version")[:HISTORY]],
    }


def _check(body: PolicyIn) -> list[int]:
    """Every rule an edit must keep; returns the thresholds, sorted and deduplicated."""
    if not 1 <= body.limit_after_days < body.restrict_after_days < body.cancel_after_days <= MAX_DAYS:
        msg = _("Days overdue must run forward: limited, then restricted, then canceled (1 to 365)")
        raise InvalidError(msg)
    if not 0 <= body.payment_terms_days <= MAX_TERMS:
        msg = _("Payment terms go from 0 to 90 days")
        raise InvalidError(msg)
    if body.small_balance < 0:
        msg = _("The small-balance threshold can't be negative")
        raise InvalidError(msg)
    if not 0 <= body.extension_days <= MAX_EXTENSION:
        msg = _("A payment extension goes from 0 to 30 days")
        raise InvalidError(msg)
    if not 1 <= body.extension_every_days <= 2 * MAX_DAYS:
        msg = _("Extensions can be offered at most once a day and at least once every two years")
        raise InvalidError(msg)
    if not 1 <= body.retention_days <= MAX_RETENTION:
        msg = _("Retention goes from 1 to 3650 days")
        raise InvalidError(msg)
    if not 0 <= body.usage_grace_hours <= MAX_GRACE_HOURS:
        msg = _("Late usage grace goes from 0 to 336 hours")
        raise InvalidError(msg)
    if not 1 <= body.spend_cap_multiple <= MAX_MULTIPLE:
        msg = _("The default spend cap goes from 1 to 10 times the plan's price")
        raise InvalidError(msg)
    thresholds = sorted(set(body.alert_thresholds))
    if not thresholds or any(t < 1 or t > MAX_PERCENT for t in thresholds):
        msg = _("Alerts go from 1% to 100% of the allowance")
        raise InvalidError(msg)
    if not body.reason.strip():
        msg = _("Say why: the reason is kept with the policy")
        raise InvalidError(msg)
    return thresholds


@transaction.atomic
def edit(body: PolicyIn, actor: tuple[str, str]) -> dict[str, Any]:
    """A new version in force from now; earlier ones stay as they were, for the record."""
    thresholds = _check(body)
    before = current()
    fields = {
        "limit_after_days": body.limit_after_days,
        "restrict_after_days": body.restrict_after_days,
        "cancel_after_days": body.cancel_after_days,
        "payment_terms_days": body.payment_terms_days,
        "small_balance": body.small_balance,
        "extension_days": body.extension_days,
        "extension_every_days": body.extension_every_days,
        "retention_days": body.retention_days,
        "usage_grace_hours": body.usage_grace_hours,
        "spend_cap_multiple": body.spend_cap_multiple,
        "alert_thresholds": thresholds,
    }
    if all(getattr(before, k) == v for k, v in fields.items()):
        msg = _("Nothing changed: the policy already reads like this")
        raise InvalidError(msg)
    last = BillingPolicy.objects.aggregate(n=Max("version"))["n"] or 0
    try:
        with transaction.atomic():
            after = BillingPolicy.objects.create(
                version=last + 1,
                effective_at=periods.now(),
                edited_by_id=actor[0],
                edited_by=actor[1],
                reason=body.reason.strip(),
                **fields,
            )
    except IntegrityError as e:
        msg = _("Someone changed the policy in the meantime: look again before changing it")
        raise ConflictError(msg) from e
    return {"before": policy_dict(before), "after": policy_dict(after)}
