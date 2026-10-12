"""Tenantly's invoices to a business: issued once per period, paid by card or by hand.

An issued invoice is never edited: its lines are the pricing quote frozen when the period
closed. `mark_paid` is the one way an invoice gets paid, whether Stripe confirmed it or
Tenantly staff recorded a transfer, so both paths behave the same and a repeat is a no-op.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.money import ZERO, wire

from ..models import BillingPeriod, PlanInvoice, PlanInvoiceLine, PlanVersion, SubscriptionChange, TenantSubscription
from . import notices, periods, policy, pricing, subscriptions, trail, usage

if TYPE_CHECKING:
    from datetime import datetime

    from common.auth import TenantClaims

VIEW = ("billing.view", "billing.manage")
NUMBER_RETRIES = 5
HISTORY = 12


def versions_of(period: BillingPeriod) -> dict[str, PlanVersion]:
    ids = {s["version"] for s in period.segments}
    return {str(v.id): v for v in PlanVersion.objects.filter(id__in=ids)}


def quote(period: BillingPeriod, sub: TenantSubscription, used: int | None = None) -> pricing.Quote:
    return pricing.quote(
        period,
        versions_of(period),
        usage.used(period) if used is None else used,
        pricing.grants_for(period.tenant_id, period.starts_at, period.ends_at),
        sub.spend_cap,
    )


def _next_number() -> int:
    return (PlanInvoice.objects.aggregate(n=Max("number"))["n"] or 0) + 1


def issue(period: BillingPeriod) -> PlanInvoice:
    """Freeze the period's quote into an invoice. One invoice per period (`UNIQUE(period)`)."""
    existing = PlanInvoice.objects.filter(period=period).first()
    if existing:
        return existing
    sub = period.subscription
    q = quote(period, sub)
    now = periods.now()
    terms = 0 if sub.payment_method == TenantSubscription.Method.STRIPE else policy.current().payment_terms_days
    for attempt in range(NUMBER_RETRIES):
        try:
            with transaction.atomic():
                invoice = PlanInvoice.objects.create(
                    tenant_id=period.tenant_id,
                    period=period,
                    number=_next_number(),
                    currency=versions_of(period)[period.segments[-1]["version"]].currency,
                    subtotal=sum((line.amount for line in q.lines if line.amount > 0), ZERO),
                    total=q.total,
                    issued_at=now,
                    due_on=now.date() + timedelta(days=terms),
                )
                break
        except IntegrityError:
            # Another invoice took that number at the same moment.
            if attempt == NUMBER_RETRIES - 1:
                raise
    PlanInvoiceLine.objects.bulk_create(
        PlanInvoiceLine(
            invoice=invoice,
            position=i,
            kind=line.kind,
            detail=line.detail,
            quantity=line.quantity,
            unit_price=line.unit_price,
            amount=line.amount,
        )
        for i, line in enumerate(q.lines)
    )
    if invoice.total <= 0:
        invoice.status = PlanInvoice.Status.PAID
        invoice.paid_at = now
        invoice.paid_via = "none"
        invoice.save(update_fields=["status", "paid_at", "paid_via"])
    notices.notify(
        period.tenant_id,
        "invoice",
        f"invoice:{invoice.id}",
        {"number": invoice.code, "total": wire(invoice.total), "dueOn": invoice.due_on.isoformat()},
    )
    return invoice


@transaction.atomic
def mark_paid(
    invoice_id: object,
    via: str,
    ref: str,
    at: datetime | None = None,
    actor: tuple[str, str] = periods.TENANTLY,
) -> PlanInvoice:
    """Idempotent: paying a paid invoice again changes nothing. `actor` signs the audit entry."""
    invoice = PlanInvoice.objects.select_for_update().filter(id=invoice_id).first()
    if not invoice:
        msg = _("No such Tenantly invoice")
        raise NotFoundError(msg)
    if invoice.status == PlanInvoice.Status.PAID:
        return invoice
    if invoice.status == PlanInvoice.Status.VOID:
        msg = _("That invoice was voided")
        raise InvalidError(msg)
    invoice.status = PlanInvoice.Status.PAID
    invoice.paid_at = at or periods.now()
    invoice.paid_via = via
    invoice.payment_ref = ref[:120]
    invoice.save(update_fields=["status", "paid_at", "paid_via", "payment_ref"])
    trail.tenantly(invoice.tenant_id, "tenantly.invoice_paid", f"{invoice.code} · {via}", actor)
    notices.notify(
        invoice.tenant_id, "paid", f"paid:{invoice.id}", {"number": invoice.code, "total": wire(invoice.total)}
    )
    sub = TenantSubscription.objects.select_for_update().get(tenant_id=invoice.tenant_id)
    owing = PlanInvoice.objects.filter(tenant_id=invoice.tenant_id, status=PlanInvoice.Status.OPEN).exists()
    if (
        sub.status == TenantSubscription.Status.CANCELED
        and not owing
        and sub.retention_until
        and periods.now().date() <= sub.retention_until
        and sub.changes.filter(kind=SubscriptionChange.Kind.CANCELED, detail__reason="nonpayment").exists()
    ):
        # Canceled for not paying, and now paid in full: everything comes back.
        subscriptions.reactivate(sub, actor)
    return invoice


def by_code(code: str) -> PlanInvoice:
    digits = code.upper().removeprefix("TNT-")
    invoice = PlanInvoice.objects.filter(number=int(digits)).first() if digits.isdigit() else None
    if not invoice:
        msg = _("No such Tenantly invoice")
        raise NotFoundError(msg)
    return invoice


# --------------------------------------------------------------- reading --


def invoice_dict(invoice: PlanInvoice, *, lines: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(invoice.id),
        "number": invoice.code,
        "periodStart": invoice.period.starts_at.isoformat(),
        "periodEnd": invoice.period.ends_at.isoformat(),
        "currency": invoice.currency,
        "total": wire(invoice.total),
        "status": invoice.status,
        "issuedOn": invoice.issued_at.date().isoformat(),
        "dueOn": invoice.due_on.isoformat(),
        "paidOn": invoice.paid_at.date().isoformat() if invoice.paid_at else None,
        "paidVia": invoice.paid_via or None,
    }
    if lines:
        out["lines"] = [
            {
                "kind": line.kind,
                "detail": line.detail,
                "quantity": line.quantity,
                "unitPrice": wire(line.unit_price) if line.unit_price is not None else None,
                "amount": wire(line.amount),
            }
            for line in invoice.lines.all()
        ]
    return out


def history(claims: TenantClaims) -> dict[str, Any]:
    claims.demand_any(VIEW)
    rows = BillingPeriod.objects.filter(tenant_id=claims.tenant_id).select_related("invoice")[:HISTORY]
    out_periods = []
    for p in rows:
        inv = getattr(p, "invoice", None)
        version = versions_of(p)[p.segments[-1]["version"]]
        out_periods.append(
            {
                "id": p.id,
                "start": p.starts_at.isoformat(),
                "end": p.ends_at.isoformat(),
                "status": p.status,
                "plan": version.name,
                "used": usage.used(p),
                "allowance": pricing.allowance_of(version, pricing.grants_for(p.tenant_id, p.starts_at, p.ends_at)),
                "invoice": invoice_dict(inv) if inv else None,
            }
        )
    sub = subscriptions.ensure(claims.tenant_id)
    changes = [
        {
            "kind": c.kind,
            "from": c.from_version.name if c.from_version else None,
            "to": c.to_version.name if c.to_version else None,
            "at": c.effective_at.isoformat(),
            "by": c.actor_name,
            "detail": c.detail,
        }
        for c in sub.changes.select_related("from_version", "to_version")[:20]
    ]
    return {"periods": out_periods, "changes": changes}


def detail(claims: TenantClaims, invoice_id: str) -> dict[str, Any]:
    claims.demand_any(VIEW)
    invoice = PlanInvoice.objects.filter(tenant_id=claims.tenant_id, id=invoice_id).select_related("period").first()
    if not invoice:
        msg = _("No such Tenantly invoice")
        raise NotFoundError(msg)
    return invoice_dict(invoice, lines=True)
