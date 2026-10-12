"""Inside one business. Authenticated with a tenant token (see common.auth)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ninja import Router

from common.auth import TenantAuth, claims_of
from common.schemas import Ok

from ..schemas import InviteIn, NodeIn, NodePatch, RoleDefIn, RoleDefPatch, RoleIn, SettingsIn
from ..services import business, roles, team, tenants, trail

if TYPE_CHECKING:
    from django.http import HttpRequest

router = Router(tags=["tenant"], auth=TenantAuth())


@router.get("/members")
def members(request: HttpRequest, scope: str | None = None) -> dict[str, Any]:
    return team.list_members(claims_of(request), scope)


@router.post("/members")
def invite(request: HttpRequest, body: InviteIn) -> dict[str, Any]:
    return team.invite(
        claims_of(request),
        email=body.email,
        new_role=body.role,
        scope_id=body.scope_id,
        name=body.name,
        password=body.password,
    )


@router.patch("/members/{member_id}", response=Ok)
def change_role(request: HttpRequest, member_id: str, body: RoleIn) -> Ok:
    team.change_role(claims_of(request), member_id, body.role)
    return Ok()


@router.get("/roles")
def list_roles(request: HttpRequest) -> dict[str, Any]:
    return roles.listing(claims_of(request))


@router.post("/roles")
def create_role(request: HttpRequest, body: RoleDefIn) -> dict[str, Any]:
    return roles.create(claims_of(request), label=body.label, summary=body.summary, permissions=body.permissions)


@router.patch("/roles/{key}")
def update_role(request: HttpRequest, key: str, body: RoleDefPatch) -> dict[str, Any]:
    return roles.update(claims_of(request), key, label=body.label, summary=body.summary, permissions=body.permissions)


@router.delete("/roles/{key}", response=Ok)
def delete_role(request: HttpRequest, key: str) -> Ok:
    roles.delete(claims_of(request), key)
    return Ok()


@router.get("/settings")
def read_settings(request: HttpRequest) -> dict[str, Any]:
    return business.read(claims_of(request))


@router.patch("/settings")
def update_settings(request: HttpRequest, body: SettingsIn) -> dict[str, Any]:
    patch = business.SettingsPatch(
        currency=body.currency,
        tax_rate=body.tax_rate,
        tax_label=body.tax_label,
        prices_include_tax=body.prices_include_tax,
        logo_url=body.logo_url,
        custom_domain=body.custom_domain,
        sso=body.sso.model_dump(by_alias=True) if body.sso else None,
    )
    return business.update(claims_of(request), patch)


@router.post("/nodes")
def add_node(request: HttpRequest, body: NodeIn) -> dict[str, Any]:
    node = tenants.add_node(
        claims_of(request), parent_id=body.parent_id, kind=body.kind, name=body.name, level=body.level
    )
    return tenants.node_dict(node)


@router.patch("/nodes/{node_id}")
def update_node(request: HttpRequest, node_id: str, body: NodePatch) -> dict[str, Any]:
    clock = tenants.ClockPatch(tz=body.tz, open=body.open, close=body.close, reset_hours=body.reset_hours)
    node = tenants.update_node(claims_of(request), node_id, name=body.name, status=body.status, clock=clock)
    return tenants.node_dict(node)


@router.get("/audit")
def audit_trail(request: HttpRequest, scope: str | None = None) -> dict[str, Any]:
    return trail.read(claims_of(request), scope)

