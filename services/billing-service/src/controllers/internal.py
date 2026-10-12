"""Service-to-service routes (operations raises charges here). Never exposed by the proxy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ninja import Router

from common.internal import InternalAuth

from ..schemas import (
    BalancesIn,
    ChargeIn,
    GrantIn,
    InvoicePaidIn,
    PlanAssignIn,
    PolicyIn,
    RepriceIn,
    RevenueIn,
    SettledIn,
    SummariesIn,
    TenantRef,
    UsageIn,
)
from ..services import charges, console, overview, policy, repricing, subscriptions, usage

if TYPE_CHECKING:
    from django.http import HttpRequest

router = Router(tags=["internal"], auth=InternalAuth())


@router.post("/charges")
def create_charge(request: HttpRequest, body: ChargeIn) -> dict[str, str]:  # noqa: ARG001
    return {"id": str(charges.create(body).id)}


@router.post("/bookings/{booking_id}/refund")
def refund_booking(request: HttpRequest, booking_id: str, body: TenantRef) -> dict[str, int]:  # noqa: ARG001
    return {"refunded": charges.refund_booking(body.tenant_id, booking_id)}


@router.post("/bookings/settled")
def settled_bookings(request: HttpRequest, body: SettledIn) -> list[str]:  # noqa: ARG001
    return charges.settled(body.tenant_id, body.booking_ids)


@router.post("/balances")
def balances(request: HttpRequest, body: BalancesIn) -> dict[str, dict[str, str]]:  # noqa: ARG001
    return charges.balances(body.tenant_id, body.customer_ids)


@router.post("/revenue")
def revenue(request: HttpRequest, body: RevenueIn) -> dict[str, dict[str, str]]:  # noqa: ARG001
    return charges.revenue_split(body.tenant_id, body.location_ids, body.start, body.end)


@router.get("/customers/{customer_id}/charges")
def customer_charges(request: HttpRequest, customer_id: str, tenant_id: str) -> list[dict[str, Any]]:  # noqa: ARG001
    return charges.customer_charges(tenant_id, customer_id)


@router.post("/usage")
def record_usage(request: HttpRequest, body: UsageIn) -> dict[str, bool]:  # noqa: ARG001
    """Operations' outbox delivers usage here; replays are no-ops."""
    return usage.record(body)


@router.get("/tenants/{tenant_id}/entitlements")
def entitlements(request: HttpRequest, tenant_id: str) -> dict[str, Any]:  # noqa: ARG001
    """What identity puts in the tenant token: plan name and payment standing."""
    return overview.entitlements(tenant_id)


@router.put("/tenants/{tenant_id}/plan")
def assign_plan(request: HttpRequest, tenant_id: str, body: PlanAssignIn) -> dict[str, Any]:  # noqa: ARG001
    """Tenantly moves a business to a plan (identity's `manage.py set_plan` or admin console)."""
    before = subscriptions.snapshot(tenant_id)
    sub = subscriptions.assign(tenant_id, body)
    return {"plan": sub.plan_version.name, "status": sub.status, "before": before}


# ------------------------------------------- the admin console (identity) --


@router.post("/admin/summaries")
def summaries(request: HttpRequest, body: SummariesIn) -> dict[str, dict[str, Any]]:  # noqa: ARG001
    """Plan, standing and usage per business; businesses without a subscription are left out."""
    return console.summaries(body.tenant_ids)


@router.get("/tenants/{tenant_id}/subscription")
def subscription(request: HttpRequest, tenant_id: str) -> dict[str, Any]:  # noqa: ARG001
    return console.detail(tenant_id)


@router.post("/tenants/{tenant_id}/grants")
def add_grant(request: HttpRequest, tenant_id: str, body: GrantIn) -> dict[str, Any]:  # noqa: ARG001
    return console.add_grant(tenant_id, body)


@router.post("/plan-invoices/{invoice_id}/paid")
def invoice_paid(request: HttpRequest, invoice_id: str, body: InvoicePaidIn) -> dict[str, Any]:  # noqa: ARG001
    return console.invoice_paid(invoice_id, body)


@router.get("/admin/plans")
def plans(request: HttpRequest) -> dict[str, Any]:  # noqa: ARG001
    """Every public plan version with its subscribers and this period's usage."""
    return repricing.listing()


@router.post("/admin/plans/{version_id}/reprice")
def reprice(request: HttpRequest, version_id: str, body: RepriceIn) -> dict[str, Any]:  # noqa: ARG001
    """A new price list for the plan; its businesses move to it at their next renewal."""
    return repricing.reprice(version_id, body, console.signer(body.actor))


@router.get("/admin/policy")
def billing_policy(request: HttpRequest) -> dict[str, Any]:  # noqa: ARG001
    return policy.overview()


@router.put("/admin/policy")
def edit_policy(request: HttpRequest, body: PolicyIn) -> dict[str, Any]:  # noqa: ARG001
    return policy.edit(body, console.signer(body.actor))
