"""The Tenantly admin console: admins only, inside their access window.

Authenticated with an admin token (`common.auth.verify_admin`: its own key and audience), so
a tenant token or session never opens these routes and an admin token opens nothing else.
The proxy serves them only on the admin host. Every request checks the admin's window again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ninja import Router
from ninja.security import HttpBearer

from ..schemas import (
    AdminGrantIn,
    AdminLoginIn,
    AdminPlanIn,
    BusinessIn,
    InvoicePaidIn,
    OwnerIn,
    OwnerStatusIn,
    PolicyIn,
    RepriceIn,
)
from ..services import admin, admins

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ..models import PlatformAdmin


class AdminAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str) -> PlatformAdmin:
        return admins.authenticate(token, admins.client_ip(request))


router = Router(tags=["admin"], auth=AdminAuth())


def _ip(request: HttpRequest) -> str:
    return admins.client_ip(request)


@router.post("/auth/login", auth=None)
def login(request: HttpRequest, body: AdminLoginIn) -> dict[str, Any]:
    found, token = admins.login(body.email, body.password, _ip(request))
    return {"token": token, "admin": admins.admin_dict(found)}


@router.get("/me")
def me(request: HttpRequest) -> dict[str, Any]:
    return admins.admin_dict(request.auth)


@router.get("/audit")
def audit(request: HttpRequest, offset: int = 0) -> dict[str, Any]:  # noqa: ARG001
    return admins.log(offset)


@router.get("/owners")
def owners(request: HttpRequest, q: str = "", offset: int = 0) -> dict[str, Any]:  # noqa: ARG001
    return admin.owners(q, offset)


@router.post("/owners")
def create_owner(request: HttpRequest, body: OwnerIn) -> dict[str, Any]:
    return admin.create_owner(request.auth, _ip(request), body)


@router.post("/owners/{user_id}/businesses")
def add_business(request: HttpRequest, user_id: str, body: BusinessIn) -> dict[str, Any]:
    return admin.add_business(request.auth, _ip(request), user_id, body)


@router.put("/owners/{user_id}/status")
def owner_status(request: HttpRequest, user_id: str, body: OwnerStatusIn) -> dict[str, Any]:
    return admin.set_owner_status(request.auth, _ip(request), user_id, body)


@router.get("/businesses/{tenant_id}/subscription")
def subscription(request: HttpRequest, tenant_id: str) -> dict[str, Any]:  # noqa: ARG001
    return admin.subscription(tenant_id)


@router.put("/businesses/{tenant_id}/plan")
def assign_plan(request: HttpRequest, tenant_id: str, body: AdminPlanIn) -> dict[str, Any]:
    return admin.assign_plan(request.auth, _ip(request), tenant_id, body)


@router.post("/businesses/{tenant_id}/grants")
def grant(request: HttpRequest, tenant_id: str, body: AdminGrantIn) -> dict[str, Any]:
    return admin.grant(request.auth, _ip(request), tenant_id, body)


@router.post("/invoices/{invoice_id}/paid")
def invoice_paid(request: HttpRequest, invoice_id: str, body: InvoicePaidIn) -> dict[str, Any]:
    return admin.invoice_paid(request.auth, _ip(request), invoice_id, body)


@router.get("/plans")
def plans(request: HttpRequest) -> dict[str, Any]:  # noqa: ARG001
    return admin.plans()


@router.post("/plans/{version_id}/reprice")
def reprice(request: HttpRequest, version_id: str, body: RepriceIn) -> dict[str, Any]:
    return admin.reprice(request.auth, _ip(request), version_id, body)


@router.get("/policy")
def policy(request: HttpRequest) -> dict[str, Any]:  # noqa: ARG001
    return admin.policy()


@router.put("/policy")
def edit_policy(request: HttpRequest, body: PolicyIn) -> dict[str, Any]:
    return admin.edit_policy(request.auth, _ip(request), body)
