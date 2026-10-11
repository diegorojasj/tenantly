"""Customer invoices (docs/PLATFORM.md gap 9): a customer's open charges under one number, with tax.

Issuing gathers every open charge of the customer the member can reach (in the tenant's
current currency) onto a new invoice. Paying the invoice collects all of them; voiding it
puts them back as plain open charges. Tax follows the tenant's settings at issue time.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.internal import audit
from common.money import ZERO, label, tax_split, wire

from ..models import Charge, Invoice

if TYPE_CHECKING:
    from collections.abc import Iterable

    from common.auth import TenantClaims

MONEY = ("payments.collect", "analytics.view")
LIST_LIMIT = 100


def invoice_dict(inv: Invoice, *, lines: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(inv.id),
        "number": inv.code,
        "customerId": str(inv.customer_id),
        "customerName": inv.customer_name,
        "locationId": str(inv.location_id),
        "currency": inv.currency,
        "taxLabel": inv.tax_label,
        "taxRate": wire(inv.tax_rate),
        "pricesIncludeTax": inv.prices_include_tax,
        "subtotal": wire(inv.subtotal),
        "tax": wire(inv.tax),
        "total": wire(inv.total),
        "status": inv.status,
        "issuedOn": inv.issued_on.isoformat(),
        "paidOn": inv.paid_on.isoformat() if inv.paid_on else None,
    }
    if lines:
        data["lines"] = [
            {"id": str(c.id), "description": c.description, "date": c.date.isoformat(), "amount": wire(c.amount)}
            for c in inv.charges.order_by("date", "created_at")
        ]
    return data


def _totals(inv: Invoice) -> None:
    gross = inv.charges.exclude(status=Charge.Status.REFUNDED).aggregate(s=Sum("amount"))["s"] or ZERO
    inv.subtotal, inv.tax, inv.total = tax_split(gross, inv.tax_rate, inclusive=inv.prices_include_tax)


def _found(claims: TenantClaims, invoice_id: str, *, lock: bool = False) -> Invoice:
    rows = Invoice.objects.select_for_update() if lock else Invoice.objects
    inv = rows.filter(tenant_id=claims.tenant_id, id=invoice_id).first()
    if not inv or not claims.reaches(str(inv.location_id)):
        msg = _("That invoice is outside your scope")
        raise NotFoundError(msg)
    return inv


def _audit(claims: TenantClaims, inv: Invoice, action: str) -> None:
    audit(
        claims,
        action,
        "billing",
        f"{inv.code} · {inv.customer_name} · {label(inv.total, inv.currency)}",
        str(inv.location_id),
    )


# ------------------------------------------------------------- reading --


def listing(claims: TenantClaims, scope: str | None) -> dict[str, Any]:
    claims.demand_any(MONEY)
    rows = Invoice.objects.filter(tenant_id=claims.tenant_id, location_id__in=claims.locations(scope))
    return {
        "canIssue": claims.can("payments.collect"),
        "invoices": [invoice_dict(i) for i in rows[:LIST_LIMIT]],
    }


def detail(claims: TenantClaims, invoice_id: str) -> dict[str, Any]:
    claims.demand_any(MONEY)
    return invoice_dict(_found(claims, invoice_id), lines=True)


# ------------------------------------------------------------- writing --


@transaction.atomic
def issue(claims: TenantClaims, customer_id: str) -> Invoice:
    claims.demand("payments.collect")
    charges = list(
        Charge.objects.select_for_update()
        .filter(
            tenant_id=claims.tenant_id,
            customer_id=customer_id,
            status=Charge.Status.DUE,
            invoice__isnull=True,
            currency=claims.currency,
            location_id__in=claims.locations(None),
        )
        .order_by("date", "created_at")
    )
    if not charges:
        msg = _("Nothing open to invoice for that customer")
        raise InvalidError(msg)
    money = claims.money
    last = Invoice.objects.filter(tenant_id=claims.tenant_id).aggregate(n=Max("number"))["n"] or 0
    inv = Invoice.objects.create(
        tenant_id=claims.tenant_id,
        number=last + 1,
        location_id=charges[0].location_id,
        customer_id=customer_id,
        customer_name=charges[0].customer_name,
        currency=claims.currency,
        tax_label=str(money.get("taxLabel") or "Tax"),
        tax_rate=Decimal(str(money.get("taxRate") or "0")),
        prices_include_tax=bool(money.get("pricesIncludeTax", True)),
        issued_on=timezone.now().date(),
    )
    Charge.objects.filter(id__in=[c.id for c in charges]).update(invoice=inv)
    _totals(inv)
    inv.save(update_fields=["subtotal", "tax", "total"])
    _audit(claims, inv, "invoice.issued")
    return inv


@transaction.atomic
def pay(claims: TenantClaims, invoice_id: str) -> Invoice:
    claims.demand("payments.collect")
    inv = _found(claims, invoice_id, lock=True)
    if inv.status != Invoice.Status.OPEN:
        msg = _("Only open invoices can be paid")
        raise InvalidError(msg)
    on = timezone.now().date()
    inv.charges.filter(status=Charge.Status.DUE).update(status=Charge.Status.PAID, paid_on=on)
    inv.status, inv.paid_on = Invoice.Status.PAID, on
    inv.save(update_fields=["status", "paid_on"])
    _audit(claims, inv, "invoice.paid")
    return inv


@transaction.atomic
def void(claims: TenantClaims, invoice_id: str) -> Invoice:
    claims.demand("payments.collect")
    inv = _found(claims, invoice_id, lock=True)
    if inv.status != Invoice.Status.OPEN:
        msg = _("Only open invoices can be voided")
        raise InvalidError(msg)
    inv.charges.update(invoice=None)
    inv.status = Invoice.Status.VOID
    inv.save(update_fields=["status"])
    _audit(claims, inv, "invoice.voided")
    return inv


def retotal(invoice_ids: Iterable[Any]) -> None:
    """Open invoices whose charges changed underneath them: total again, or void when empty."""
    for inv in Invoice.objects.select_for_update().filter(id__in=list(invoice_ids), status=Invoice.Status.OPEN):
        if not inv.charges.exists():
            inv.status = Invoice.Status.VOID
        _totals(inv)
        inv.save(update_fields=["status", "subtotal", "tax", "total"])
