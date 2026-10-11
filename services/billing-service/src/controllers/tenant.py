"""Payments inside one business. Authenticated with a tenant token."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from ninja import Router

from common.auth import TenantAuth, claims_of

from ..schemas import InvoiceIn
from ..services import charges, invoices, plans

if TYPE_CHECKING:
    from django.http import HttpRequest

router = Router(tags=["payments"], auth=TenantAuth())


@router.get("/payments")
def payments(request: HttpRequest, scope: str | None = None) -> dict[str, Any]:
    return charges.payments(claims_of(request), scope)


@router.post("/charges/{charge_id}/collect")
def collect(request: HttpRequest, charge_id: str) -> dict[str, Any]:
    charge = charges.settle(claims_of(request), charge_id, "collect")
    return charges.charge_dict(charge, charges.today())


@router.post("/charges/{charge_id}/refund")
def refund(request: HttpRequest, charge_id: str) -> dict[str, Any]:
    charge = charges.settle(claims_of(request), charge_id, "refund")
    return charges.charge_dict(charge, charges.today())


@router.get("/revenue")
def revenue(request: HttpRequest, start: date, end: date, scope: str | None = None) -> dict[str, str]:
    return charges.revenue(claims_of(request), scope, start, end)


@router.get("/plan")
def plan(request: HttpRequest) -> dict[str, Any]:
    return plans.usage(claims_of(request))


@router.get("/invoices")
def list_invoices(request: HttpRequest, scope: str | None = None) -> dict[str, Any]:
    return invoices.listing(claims_of(request), scope)


@router.post("/invoices")
def issue_invoice(request: HttpRequest, body: InvoiceIn) -> dict[str, Any]:
    return invoices.invoice_dict(invoices.issue(claims_of(request), body.customer_id), lines=True)


@router.get("/invoices/{invoice_id}")
def invoice(request: HttpRequest, invoice_id: str) -> dict[str, Any]:
    return invoices.detail(claims_of(request), invoice_id)


@router.post("/invoices/{invoice_id}/pay")
def pay_invoice(request: HttpRequest, invoice_id: str) -> dict[str, Any]:
    return invoices.invoice_dict(invoices.pay(claims_of(request), invoice_id))


@router.post("/invoices/{invoice_id}/void")
def void_invoice(request: HttpRequest, invoice_id: str) -> dict[str, Any]:
    return invoices.invoice_dict(invoices.void(claims_of(request), invoice_id))
