"""What a period costs: the same maths for the live estimate and the invoice (docs/BILLING.md §4).

- The base price of each plan version in force, prorated by the share of the month it covered.
- Overage: active customers past the allowance (the last version's, plus extra granted),
  at that version's price per customer.
- A cap: the period total never passes the version's `overage_cap` (the next tier's price,
  so growing is never worse than upgrading) or, on the top tier, the business's spend cap
  (by default the billing policy's multiple of the base price).
- Discounts Tenantly granted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from common.money import CENT, ZERO, wire

from ..models import EntitlementGrant
from . import policy
from .periods import month_start, next_month

if TYPE_CHECKING:
    from ..models import BillingPeriod, PlanVersion

METRIC = "active_customers"
HUNDRED = Decimal(100)
# Too early in the period to say where it's heading.
MIN_SHARE_TO_PROJECT = 0.1


@dataclass
class Line:
    kind: str
    amount: Decimal
    quantity: int = 1
    unit_price: Decimal | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "amount": wire(self.amount),
            "quantity": self.quantity,
            "unitPrice": wire(self.unit_price) if self.unit_price is not None else None,
            "detail": self.detail,
        }


@dataclass
class Quote:
    lines: list[Line]
    allowance: int | None
    cap: Decimal | None

    @property
    def total(self) -> Decimal:
        return max(ZERO, sum((line.amount for line in self.lines), ZERO))


def grants_for(tenant_id: object, start: datetime, end: datetime) -> list[EntitlementGrant]:
    return list(EntitlementGrant.objects.filter(tenant_id=tenant_id, valid_from__lt=end, valid_until__gt=start))


def default_spend_cap(version: PlanVersion) -> Decimal:
    """A top-tier period with no cap of its own bills at most the policy's multiple of its base price."""
    return (version.base_price * policy.current().spend_cap_multiple).quantize(CENT)


def cap_of(version: PlanVersion, spend_cap: Decimal | None) -> Decimal | None:
    """The ceiling on a period's total; None when the version has no overage to cap."""
    if version.unit_price(METRIC) is None:
        return None
    if version.overage_cap is not None:
        return version.overage_cap
    return spend_cap if spend_cap is not None else default_spend_cap(version)


def allowance_of(version: PlanVersion, grants: list[EntitlementGrant]) -> int | None:
    base = version.allowance(METRIC)
    if base is None:
        return None
    extra = sum(int(g.value) for g in grants if g.kind == EntitlementGrant.Kind.EXTRA_ALLOWANCE and g.metric == METRIC)
    return base + extra


def _base_lines(period: BillingPeriod, versions: dict[str, PlanVersion]) -> list[Line]:
    month = month_start(period.starts_at)
    full = Decimal(int((next_month(month) - month).total_seconds()))
    lines: list[Line] = []
    segments = period.segments
    for i, seg in enumerate(segments):
        version = versions[seg["version"]]
        since = max(datetime.fromisoformat(seg["from"]), period.starts_at)
        until = datetime.fromisoformat(segments[i + 1]["from"]) if i + 1 < len(segments) else period.ends_at
        until = min(until, period.ends_at)
        seconds = Decimal(int((until - since).total_seconds()))
        if seconds <= 0:
            continue
        amount = version.base_price if seconds == full else (version.base_price * seconds / full).quantize(CENT)
        lines.append(
            Line(
                "base",
                amount,
                unit_price=version.base_price,
                detail={
                    "plan": version.name,
                    "version": version.version,
                    "from": since.isoformat(),
                    "until": until.isoformat(),
                    "prorated": seconds != full,
                },
            )
        )
    return lines


def quote(
    period: BillingPeriod,
    versions: dict[str, PlanVersion],
    used: int,
    grants: list[EntitlementGrant],
    spend_cap: Decimal | None,
) -> Quote:
    version = versions[period.segments[-1]["version"]]
    lines = _base_lines(period, versions)
    allowance = allowance_of(version, grants)
    unit = version.unit_price(METRIC)
    waived = any(g.kind == EntitlementGrant.Kind.WAIVE_OVERAGE for g in grants)
    over = max(0, used - allowance) if allowance is not None else 0
    cap = cap_of(version, spend_cap)
    if over and unit is not None and not waived:
        lines.append(
            Line(
                "overage",
                (unit * over).quantize(CENT),
                quantity=over,
                unit_price=unit,
                detail={"allowance": allowance, "used": used},
            )
        )
        subtotal = sum((line.amount for line in lines), ZERO)
        if cap is not None and subtotal > cap:
            lines.append(Line("cap", cap - subtotal, detail={"cap": wire(cap)}))
    pct = min(HUNDRED, sum((g.value for g in grants if g.kind == EntitlementGrant.Kind.DISCOUNT_PCT), ZERO))
    if pct > 0:
        subtotal = sum((line.amount for line in lines), ZERO)
        lines.append(Line("discount", -(subtotal * pct / HUNDRED).quantize(CENT), detail={"percent": str(pct)}))
    return Quote(lines=lines, allowance=allowance, cap=cap)


def projected(used: int, period: BillingPeriod, at: datetime) -> int | None:
    """Where usage lands by the period's end at this pace; None too early to tell."""
    span = (period.ends_at - period.starts_at).total_seconds()
    share = (min(at, period.ends_at) - period.starts_at).total_seconds() / span
    if share < MIN_SHARE_TO_PROJECT:
        return None
    return math.ceil(used / share)
