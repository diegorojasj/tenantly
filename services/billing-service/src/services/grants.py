"""Exceptions Tenantly authorises for one business (docs/BILLING.md §5): extra allowance, a
discount, waived overage, more grace, or a dispute that pauses collections.

Each one is bounded in time, carries a reason and who approved it, and lands in the
business's audit trail. Only Tenantly grants them: `manage.py grant` or the admin console.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.money import wire

from ..models import EntitlementGrant, TenantSubscription
from . import periods, pricing, trail

if TYPE_CHECKING:
    from decimal import Decimal

MAX_PERCENT = 100


@transaction.atomic
def grant(
    tenant_id: object,
    kind: str,
    *,
    metric: str,
    value: Decimal,
    days: int,
    reason: str,
    actor: tuple[str, str] = periods.TENANTLY,
) -> EntitlementGrant:
    """Never creates the subscription: a business without one has nothing to grant on."""
    if not TenantSubscription.objects.filter(tenant_id=tenant_id).exists():
        msg = _("This business has no Tenantly subscription yet")
        raise NotFoundError(msg)
    if kind == EntitlementGrant.Kind.EXTRA_ALLOWANCE and metric != pricing.METRIC:
        msg = _("Extra allowance needs the metric it adds to")
        raise InvalidError(msg)
    if kind == EntitlementGrant.Kind.DISCOUNT_PCT and not 0 < value <= MAX_PERCENT:
        msg = _("A discount goes from 1% to 100%")
        raise InvalidError(msg)
    if days < 1:
        msg = _("A grant lasts at least a day")
        raise InvalidError(msg)
    if not reason.strip():
        msg = _("Say why: the reason is kept with the grant")
        raise InvalidError(msg)
    at = periods.now()
    created = EntitlementGrant.objects.create(
        tenant_id=tenant_id,
        kind=kind,
        metric=metric if kind == EntitlementGrant.Kind.EXTRA_ALLOWANCE else "",
        value=value,
        valid_from=at,
        valid_until=at + timedelta(days=days),
        reason=reason.strip(),
        approved_by=actor[1],
    )
    trail.tenantly(tenant_id, "tenantly.grant", f"{created.kind} {created.value} · {created.reason}", actor)
    return created


def grant_dict(g: EntitlementGrant) -> dict[str, Any]:
    return {
        "id": g.id,
        "kind": g.kind,
        "metric": g.metric,
        "value": wire(g.value),
        "validFrom": g.valid_from.isoformat(),
        "validUntil": g.valid_until.isoformat(),
        "reason": g.reason,
        "approvedBy": g.approved_by,
    }
