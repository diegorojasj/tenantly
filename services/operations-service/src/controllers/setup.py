"""Set up: Catalog, Resources, Policies. Tenant-token auth."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ninja import Router

from common.auth import TenantAuth, claims_of
from common.schemas import Ok

from ..schemas import OfferingIn, PolicyIn, ResourceIn, ResourceStatusIn
from ..services import catalog, policies, resources, shape

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


@router.get("/policies")
def read_policies(request: HttpRequest, scope: str | None = None) -> list[dict[str, Any]]:
    return policies.read(claims_of(request), scope)


@router.put("/policies", response=Ok)
def write_policy(request: HttpRequest, body: PolicyIn) -> Ok:
    policies.write(claims_of(request), body.scope, body.key, body.value)
    return Ok()
