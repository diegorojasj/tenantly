"""The Tenantly plan catalog: versioned prices, never edited once offered (docs/BILLING.md §4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Max, Q
from django.utils.translation import gettext as _

from common.errors import InvalidError
from common.money import wire

from ..models import PlanVersion
from . import pricing

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

PUBLIC = ("starter", "growth", "enterprise")
CUSTOM = "custom"
CUSTOM_RANK = 10


def offered() -> list[PlanVersion]:
    """The public price list: the newest active version of each tier."""
    rows = PlanVersion.objects.filter(tenant_id__isnull=True, status=PlanVersion.Status.ACTIVE, code__in=PUBLIC)
    newest: dict[str, PlanVersion] = {}
    for v in rows.order_by("code", "-version"):
        newest.setdefault(v.code, v)
    return sorted(newest.values(), key=lambda v: v.rank)


def public(code: str) -> PlanVersion:
    found = next((v for v in offered() if v.code == code), None)
    if not found:
        msg = _("That plan isn't offered")
        raise InvalidError(msg)
    return found


def in_force(code: str, at: datetime) -> PlanVersion:
    """The public version of a tier on sale at `at`; the first one for businesses older than the catalog."""
    versions = PlanVersion.objects.filter(
        tenant_id__isnull=True, code=code, status__in=(PlanVersion.Status.ACTIVE, PlanVersion.Status.LEGACY)
    )
    found = versions.filter(effective_from__lte=at).order_by("-effective_from", "-version").first()
    return found or versions.order_by("effective_from", "version").first() or public(code)


def custom(
    tenant_id: object, price: Decimal, customer_limit: int | None, overage: Decimal | None, at: datetime
) -> PlanVersion:
    """A Custom plan is a private version: the business's own price list."""
    last = PlanVersion.objects.filter(code=CUSTOM, tenant_id=tenant_id).aggregate(n=Max("version"))["n"] or 0
    PlanVersion.objects.filter(Q(code=CUSTOM, tenant_id=tenant_id) & Q(status=PlanVersion.Status.ACTIVE)).update(
        status=PlanVersion.Status.LEGACY
    )
    return PlanVersion.objects.create(
        code=CUSTOM,
        version=last + 1,
        name="Custom",
        tenant_id=tenant_id,
        base_price=price,
        included={pricing.METRIC: customer_limit} if customer_limit else {},
        overage_price={pricing.METRIC: str(overage)} if overage is not None and customer_limit else {},
        rank=CUSTOM_RANK,
        status=PlanVersion.Status.ACTIVE,
        effective_from=at,
    )


def plan_dict(v: PlanVersion) -> dict[str, Any]:
    unit = v.unit_price(pricing.METRIC)
    return {
        "id": str(v.id),
        "code": v.code,
        "name": v.name,
        "version": v.version,
        "legacy": v.status == PlanVersion.Status.LEGACY,
        "custom": v.tenant_id is not None,
        "currency": v.currency,
        "price": wire(v.base_price),
        "included": v.allowance(pricing.METRIC),
        "overagePrice": wire(unit) if unit is not None else None,
        "cap": wire(v.overage_cap) if v.overage_cap is not None else None,
        "rank": v.rank,
    }
