"""Set up: Catalog, Resources (and their downtime), Policies. Tenant-token auth."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ninja import Router

from common.auth import TenantAuth, claims_of
from common.schemas import Ok

from ..schemas import DowntimeIn, DowntimeMoneyIn, OfferingIn, PolicyIn, ResourceIn, ResourceStatusIn
from ..services import catalog, downtimes, policies, resources, shape

if TYPE_CHECKING:
    from django.http import HttpRequest

router = Router(tags=["setup"], auth=TenantAuth())


@router.get("/catalog")
def read_catalog(request: HttpRequest, scope: str | None = None) -> dict[str, Any]:
    return catalog.read(claims_of(request), scope)


@router.post("/offerings")
def create_offering(request: HttpRequest, body: OfferingIn) -> dict[str, Any]:
    return shape.offering(catalog.create(claims_of(request), body))


@router.post("/offerings/{offering_id}/toggle")
def toggle_offering(request: HttpRequest, offering_id: str) -> dict[str, Any]:
    return shape.offering(catalog.toggle(claims_of(request), offering_id))


@router.get("/resources")
def read_resources(request: HttpRequest, scope: str | None = None) -> dict[str, Any]:
    return resources.read(claims_of(request), scope)


@router.post("/resources")
def create_resource(request: HttpRequest, body: ResourceIn) -> dict[str, Any]:
    return shape.resource(resources.create(claims_of(request), body))


@router.post("/resources/{resource_id}/status")
def resource_status(request: HttpRequest, resource_id: str, body: ResourceStatusIn) -> dict[str, Any]:
    return shape.resource(resources.set_status(claims_of(request), resource_id, body.status))


@router.get("/downtimes")
def read_downtimes(request: HttpRequest, scope: str | None = None) -> dict[str, Any]:
    return downtimes.read(claims_of(request), scope)


@router.post("/downtimes")
def create_downtime(request: HttpRequest, body: DowntimeIn) -> dict[str, str]:
    return {"id": str(downtimes.create(claims_of(request), body).id)}


@router.post("/downtimes/{downtime_id}/end")
def end_downtime(request: HttpRequest, downtime_id: str) -> dict[str, bool]:
    """Back in use now; one that hasn't started is withdrawn."""
    return {"withdrawn": downtimes.finish(claims_of(request), downtime_id) is None}


@router.post("/downtimes/{downtime_id}/money", response=Ok)
def downtime_money(request: HttpRequest, downtime_id: str, body: DowntimeMoneyIn) -> Ok:
    downtimes.record_money(claims_of(request), downtime_id, body)
    return Ok()


@router.get("/policies")
def read_policies(request: HttpRequest, scope: str | None = None) -> list[dict[str, Any]]:
    return policies.read(claims_of(request), scope)


@router.put("/policies", response=Ok)
def write_policy(request: HttpRequest, body: PolicyIn) -> Ok:
    policies.write(claims_of(request), body.scope, body.key, body.value)
    return Ok()
