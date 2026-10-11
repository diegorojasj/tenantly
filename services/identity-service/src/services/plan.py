"""The business's Tenantly plan as identity keeps it: its name and, for Custom, its terms.

Prices, limits and the automatic move up a tier are billing's (billing/services/plans.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError

from ..models import Tenant
from . import ledger

if TYPE_CHECKING:
    from ..schemas import PlanIn

TENANTLY = "Tenantly"


def _tenant(tenant_id: str) -> Tenant:
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if not tenant:
        msg = _("Unknown tenant")
        raise NotFoundError(msg)
    return tenant


def held(tenant_id: str) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    return {"plan": tenant.plan, "terms": tenant.plan_terms if tenant.plan == "Custom" else None}


def assign(tenant_id: str, body: PlanIn) -> dict[str, Any]:
    """Move a business to a plan. Custom needs its negotiated terms; the tiers take none."""
    if (body.plan == "Custom") != (body.terms is not None):
        msg = _("A Custom plan needs its terms, and only a Custom plan takes them")
        raise InvalidError(msg)
    tenant = _tenant(tenant_id)
    tenant.plan = body.plan
    tenant.plan_terms = body.terms.model_dump(mode="json", by_alias=True) if body.terms else {}
    tenant.save(update_fields=["plan", "plan_terms"])
    ledger.append(
        tenant_id,
        {
            "actor_id": TENANTLY,
            "actor_name": TENANTLY,
            "action": "plan.changed",
            "category": "billing",
            "target": body.plan,
        },
    )
    return held(tenant_id)
