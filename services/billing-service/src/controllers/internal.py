"""Service-to-service routes (operations raises charges here). Never exposed by the proxy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ninja import Router

from common.internal import InternalAuth

from ..schemas import BalancesIn, ChargeIn, RevenueIn, TenantRef
from ..services import charges

if TYPE_CHECKING:
    from django.http import HttpRequest

router = Router(tags=["internal"], auth=InternalAuth())


@router.post("/charges")
def create_charge(request: HttpRequest, body: ChargeIn) -> dict[str, str]:  # noqa: ARG001
    return {"id": str(charges.create(body).id)}


@router.post("/bookings/{booking_id}/refund")
def refund_booking(request: HttpRequest, booking_id: str, body: TenantRef) -> dict[str, int]:  # noqa: ARG001
    return {"refunded": charges.refund_booking(body.tenant_id, booking_id)}


@router.post("/balances")
def balances(request: HttpRequest, body: BalancesIn) -> dict[str, dict[str, str]]:  # noqa: ARG001
    return charges.balances(body.tenant_id, body.customer_ids)


@router.post("/revenue")
def revenue(request: HttpRequest, body: RevenueIn) -> dict[str, dict[str, str]]:  # noqa: ARG001
    return charges.revenue_split(body.tenant_id, body.location_ids, body.start, body.end)


@router.get("/customers/{customer_id}/charges")
def customer_charges(request: HttpRequest, customer_id: str, tenant_id: str) -> list[dict[str, Any]]:  # noqa: ARG001
    return charges.customer_charges(tenant_id, customer_id)
