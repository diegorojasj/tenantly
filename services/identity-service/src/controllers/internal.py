"""Service-to-service routes. The proxy never exposes /internal/."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.translation import gettext as _
from ninja import Router

from common.errors import NotFoundError
from common.internal import InternalAuth

from ..models import Tenant
from ..schemas import AuditIn
from ..services import ledger, plan

if TYPE_CHECKING:
    from django.http import HttpRequest

router = Router(tags=["internal"], auth=InternalAuth())


@router.post("/audit")
def record(request: HttpRequest, body: AuditIn) -> dict[str, str]:  # noqa: ARG001
    if not Tenant.objects.filter(id=body.tenant_id).exists():
        msg = _("Unknown tenant")
        raise NotFoundError(msg)
    event = ledger.append(
        body.tenant_id,
        {
            "actor_id": body.actor_id,
            "actor_name": body.actor_name,
            "action": body.action,
            "category": body.category,
            "target": body.target,
            "scope_id": body.scope_id,
            "scope_name": body.scope_name,
        },
    )
    return {"hash": event.hash}


@router.get("/tenants/{tenant_id}/plan")
def held_plan(request: HttpRequest, tenant_id: str) -> dict[str, object]:  # noqa: ARG001
    """The plan identity held before billing owned it; billing imports it once."""
    return plan.held(tenant_id)
