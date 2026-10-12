"""The Tenantly plan, as far as identity is concerned: billing owns it (docs/BILLING.md).

- `held` is what identity stored before billing owned subscriptions (`Tenant.plan` and
  `plan_terms`); billing reads it once, when it first creates a business's subscription.
- `assign` is Tenantly staff moving a business to a plan (`manage.py set_plan`), forwarded
  to billing, which prices it, records it and writes the audit entry.
- `entitlements` is what the tenant token carries: the plan's name and payment standing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.utils.translation import gettext as _

from common.errors import ApiError, NotFoundError
from common.internal import call

from ..models import Tenant

if TYPE_CHECKING:
    from ..schemas import PlanIn

log = logging.getLogger(__name__)


def _tenant(tenant_id: str) -> Tenant:
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if not tenant:
        msg = _("Unknown tenant")
        raise NotFoundError(msg)
    return tenant


def held(tenant_id: str) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    return {
        "plan": tenant.plan,
        "terms": tenant.plan_terms if tenant.plan == "Custom" else None,
        "since": tenant.created_at.isoformat(),
    }


def assign(tenant_id: str, body: PlanIn) -> dict[str, Any]:
    _tenant(tenant_id)
    terms = body.terms.model_dump(mode="json", by_alias=True, exclude_none=True) if body.terms else None
    return call(
        "billing",
        "PUT",
        f"/internal/tenants/{tenant_id}/plan",
        json={"plan": body.plan.lower(), "terms": terms, "reason": body.reason},
    )


def entitlements(tenant_id: str) -> dict[str, Any]:
    """Billing's answer, or nothing when it can't be reached: a billing outage never locks anyone out."""
    try:
        return call("billing", "GET", f"/internal/tenants/{tenant_id}/entitlements")
    except (ApiError, RuntimeError) as exc:
        log.warning("billing entitlements for %s unavailable: %s", tenant_id, exc)
        return {}
