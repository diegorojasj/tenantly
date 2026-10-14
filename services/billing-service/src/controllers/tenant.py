"""Payments inside one business. Authenticated with a tenant token."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

from ninja import Router

from common.auth import TenantAuth, claims_of

from ..schemas import CardIn, InvoiceIn, ManualEntryIn, PlanChangeIn, PlanSettingsIn
from ..services import charges, invoices, ledger, notices, overview, statements, stripe, subscriptions, usage

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


@router.get("/bookings/{booking_id}/charges")
def booking_charges(request: HttpRequest, booking_id: uuid.UUID) -> dict[str, Any]:
    return charges.for_booking(claims_of(request), str(booking_id))


@router.get("/revenue")
def revenue(request: HttpRequest, start: date, end: date, scope: str | None = None) -> dict[str, str]:
    return charges.revenue(claims_of(request), scope, start, end)


def _key(request: HttpRequest) -> str | None:
    """The client's Idempotency-Key: a retried change finds the one it already made."""
    return (request.headers.get("Idempotency-Key") or "")[:64] or None


# ------------------------------------------- expenses and other income --


@router.get("/ledger")
def read_ledger(
    request: HttpRequest, scope: str | None = None, start: date | None = None, end: date | None = None
) -> dict[str, Any]:
    return ledger.read(claims_of(request), scope, start, end)


@router.post("/ledger")
def add_entry(request: HttpRequest, body: ManualEntryIn) -> dict[str, Any]:
    return ledger.entry_dict(ledger.add(claims_of(request), body, _key(request)))


@router.post("/ledger/{entry_id}/void")
def void_entry(request: HttpRequest, entry_id: uuid.UUID) -> dict[str, Any]:
    return ledger.entry_dict(ledger.void(claims_of(request), str(entry_id)))


# ------------------------------------------------- the Tenantly plan --


@router.get("/plan")
def plan(request: HttpRequest) -> dict[str, Any]:
    return overview.overview(claims_of(request))


@router.get("/plan/history")
def plan_history(request: HttpRequest) -> dict[str, Any]:
    return statements.history(claims_of(request))


@router.get("/plan/customers")
def plan_customers(request: HttpRequest, period: int | None = None, offset: int = 0) -> dict[str, Any]:
    return usage.counted(claims_of(request), period, max(0, offset))


@router.get("/plan/invoices/{invoice_id}")
def plan_invoice(request: HttpRequest, invoice_id: uuid.UUID) -> dict[str, Any]:
    return statements.detail(claims_of(request), str(invoice_id))


@router.post("/plan/change")
def change_plan(request: HttpRequest, body: PlanChangeIn) -> dict[str, Any]:
    claims = claims_of(request)
    subscriptions.change_plan(claims, body.plan, body.revision, _key(request))
    return overview.overview(claims)


@router.post("/plan/withdraw")
def withdraw_change(request: HttpRequest, revision: int) -> dict[str, Any]:
    claims = claims_of(request)
    subscriptions.withdraw(claims, revision, _key(request))
    return overview.overview(claims)


@router.post("/plan/cancel")
def cancel_plan(request: HttpRequest, revision: int) -> dict[str, Any]:
    claims = claims_of(request)
    subscriptions.cancel(claims, revision, _key(request))
    return overview.overview(claims)


@router.post("/plan/resume")
def resume_plan(request: HttpRequest, revision: int) -> dict[str, Any]:
    claims = claims_of(request)
    subscriptions.resume(claims, revision, _key(request))
    return overview.overview(claims)


@router.put("/plan/settings")
def plan_settings(request: HttpRequest, body: PlanSettingsIn) -> dict[str, Any]:
    claims = claims_of(request)
    subscriptions.update_settings(claims, body)
    return overview.overview(claims)


@router.post("/plan/extension")
def plan_extension(request: HttpRequest) -> dict[str, Any]:
    claims = claims_of(request)
    subscriptions.extend(claims, _key(request))
    return overview.overview(claims)


@router.post("/plan/card")
def plan_card(request: HttpRequest, body: CardIn) -> dict[str, str]:
    return stripe.card_session(claims_of(request), body.return_url)


@router.post("/plan/notices/{notice_id}/read")
def read_notice(request: HttpRequest, notice_id: int) -> dict[str, bool]:
    notices.mark_read(claims_of(request), notice_id)
    return {"ok": True}


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
