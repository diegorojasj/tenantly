"""The tenant's Tenantly plan: prices and limits live here, not in the frontend (gap 9).

Plans are priced on consumption, not seats: how many customers the business served this
month and how many payments it took. Each tier doubles the one before it; Starter fits a
small business serving 20-50 customers a month. A month that outgrows the chosen tier is
billed on the smallest tier that fits, so nothing stops working at a limit, and the next
month starts again from the chosen plan. Past Enterprise, the owner agrees a Custom plan
with Tenantly: its own price, and limits only if they were agreed.

Tenantly bills its tenants in USD whatever currency the tenant charges in. Which plan a
tenant chose, and a Custom plan's terms, belong to identity, read over the internal API.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from common.internal import call
from common.money import wire

from . import charges

if TYPE_CHECKING:
    from common.auth import TenantClaims

PLAN_CURRENCY = "USD"
DECEMBER = 12

# Smallest first: the automatic move up walks this order.
TIERS: dict[str, dict[str, Any]] = {
    "Starter": {"price": Decimal("29.00"), "customerLimit": 50, "paymentLimit": 500},
    "Growth": {"price": Decimal("49.00"), "customerLimit": 100, "paymentLimit": 1_000},
    "Enterprise": {"price": Decimal("89.00"), "customerLimit": 200, "paymentLimit": 2_000},
}
CUSTOM = "Custom"
DEFAULT_PLAN = "Starter"


def _first_of_next_month(today: date) -> date:
    return date(today.year + 1, 1, 1) if today.month == DECEMBER else date(today.year, today.month + 1, 1)


def _fits(limit: int | None, used: int) -> bool:
    return limit is None or used <= limit


def _custom(terms: dict[str, Any]) -> dict[str, Any]:
    return {
        "price": Decimal(str(terms["price"])),
        "customerLimit": terms.get("customerLimit"),
        "paymentLimit": terms.get("paymentLimit"),
    }


def billed_tier(chosen: str, customers: int, payments: int) -> tuple[str, bool]:
    """The tier this month is billed on, and whether usage has outgrown even Enterprise.

    Never below the chosen tier; above it only when the month's usage passed its limits.
    """
    names = list(TIERS)
    for name in names[names.index(chosen) :]:
        tier = TIERS[name]
        if _fits(tier["customerLimit"], customers) and _fits(tier["paymentLimit"], payments):
            return name, False
    return names[-1], True


def usage(claims: TenantClaims) -> dict[str, Any]:
    claims.demand_any(("billing.view", "billing.manage"))
    held = call("identity", "GET", f"/internal/tenants/{claims.tenant_id}/plan")
    customers, payments, collected = charges.month_usage(claims.tenant_id)

    if held["plan"] == CUSTOM and held.get("terms"):
        chosen = billed = CUSTOM
        terms = _custom(held["terms"])
        outgrown = False
    else:
        chosen = held["plan"] if held["plan"] in TIERS else DEFAULT_PLAN
        billed, outgrown = billed_tier(chosen, customers, payments)
        terms = TIERS[billed]

    return {
        "plan": chosen,
        # The tier this month is billed on: above `plan` when usage passed its limits.
        "billedPlan": billed,
        "outgrown": outgrown,
        "currency": PLAN_CURRENCY,
        "price": wire(terms["price"]),
        "customers": {"used": customers, "limit": terms["customerLimit"]},
        "payments": {"used": payments, "limit": terms["paymentLimit"]},
        # In the tenant's own currency: what its customers paid this month.
        "collectedThisMonth": {"amount": wire(collected), "currency": claims.currency},
        "nextInvoice": {
            "date": _first_of_next_month(charges.today()).isoformat(),
            "estimate": wire(terms["price"]),
        },
        "plans": [
            *(
                {
                    "name": k,
                    "price": wire(v["price"]),
                    "customerLimit": v["customerLimit"],
                    "paymentLimit": v["paymentLimit"],
                }
                for k, v in TIERS.items()
            ),
            # Negotiated per business: no list price or limits to show.
            {"name": CUSTOM, "price": None, "customerLimit": None, "paymentLimit": None},
        ],
    }
