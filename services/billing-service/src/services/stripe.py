"""Stripe, for businesses that pay Tenantly by card (docs/BILLING.md §7.5).

Without `STRIPE_SECRET_KEY` everything is manual: invoices carry 14-day terms and staff
record payments (`manage.py mark_paid`). With it, an owner saves a card through Stripe
Checkout (setup mode), and each invoice is charged off-session when issued, again on days 3
and 7 if it failed. Webhooks are verified, stored in `ProviderEvent` before they're applied
(a duplicate stops at its unique key), and only ever move an invoice forward: a failure
reported after the payment succeeded is recorded and skipped.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from common.errors import InvalidError, UnavailableError
from common.money import CENT, HUNDRED

from ..models import PlanInvoice, ProviderEvent, SubscriptionChange, TenantSubscription
from . import notices, periods, statements, subscriptions

if TYPE_CHECKING:
    from common.auth import TenantClaims

log = logging.getLogger(__name__)

API = "https://api.stripe.com/v1"
PROVIDER = "stripe"
TOLERANCE_SECONDS = 300
TIMEOUT_SECONDS = 10.0
DECLINED = 402

# Tests swap in an httpx.MockTransport.
_transport: httpx.BaseTransport | None = None


def use_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport  # noqa: PLW0603
    _transport = transport


def configured() -> bool:
    return bool(getattr(settings, "STRIPE_SECRET_KEY", ""))


class CardDeclinedError(Exception):
    pass


def _request(method: str, path: str, data: dict[str, Any] | None = None, key: str | None = None) -> dict[str, Any]:
    headers = {"Idempotency-Key": key} if key else {}
    try:
        with httpx.Client(base_url=API, timeout=TIMEOUT_SECONDS, transport=_transport) as client:
            response = client.request(method, path, data=data, headers=headers, auth=(settings.STRIPE_SECRET_KEY, ""))
    except httpx.HTTPError as exc:
        log.warning("stripe %s %s failed: %s", method, path, exc)
        msg = _("The card processor is unavailable — try again in a moment")
        raise UnavailableError(msg) from exc
    body = response.json() if response.content else {}
    if response.status_code == DECLINED:
        raise CardDeclinedError(str(body.get("error", {}).get("message", "declined"))[:200])
    if response.status_code >= 400:  # noqa: PLR2004
        log.warning("stripe %s %s answered %s: %s", method, path, response.status_code, body)
        msg = _("The card processor refused the request")
        raise UnavailableError(msg)
    return body


# ---------------------------------------------------------------- cards --


def card_session(claims: TenantClaims, return_url: str) -> dict[str, str]:
    """A Stripe Checkout page (setup mode) where the owner saves the card Tenantly charges."""
    subscriptions.demand_owner(claims)
    if not configured():
        msg = _("Card payments aren't available yet: Tenantly invoices are paid by transfer")
        raise InvalidError(msg)
    app = settings.APP_URL.rstrip("/")
    if not (return_url == app or return_url.startswith(f"{app}/")):
        msg = _("That return address isn't Tenantly's")
        raise InvalidError(msg)
    with transaction.atomic():
        sub = subscriptions.locked(claims.tenant_id)
        if not sub.stripe_customer_id:
            customer = _request(
                "POST",
                "/customers",
                {"description": claims.tenant_slug, "metadata[tenant_id]": claims.tenant_id},
                key=f"customer-{sub.id}",
            )
            sub.stripe_customer_id = customer["id"]
            sub.save(update_fields=["stripe_customer_id"])
    session = _request(
        "POST",
        "/checkout/sessions",
        {
            "mode": "setup",
            "currency": "usd",
            "customer": sub.stripe_customer_id,
            "payment_method_types[]": "card",
            "success_url": f"{return_url}?card=saved",
            "cancel_url": return_url,
            "metadata[tenant_id]": claims.tenant_id,
        },
    )
    return {"url": session["url"]}


def charge(invoice: PlanInvoice) -> bool:
    """Try the saved card once for an open invoice. True when it's paid."""
    sub = TenantSubscription.objects.get(tenant_id=invoice.tenant_id)
    if invoice.status != PlanInvoice.Status.OPEN or not (configured() and sub.stripe_payment_method_id):
        return False
    attempt = invoice.attempts + 1
    PlanInvoice.objects.filter(id=invoice.id).update(attempts=attempt, last_attempt_on=periods.now().date())
    try:
        intent = _request(
            "POST",
            "/payment_intents",
            {
                "amount": int((invoice.total * HUNDRED).quantize(CENT)),
                "currency": invoice.currency.lower(),
                "customer": sub.stripe_customer_id,
                "payment_method": sub.stripe_payment_method_id,
                "off_session": "true",
                "confirm": "true",
                "description": invoice.code,
                "metadata[invoice_id]": str(invoice.id),
                "metadata[tenant_id]": str(invoice.tenant_id),
            },
            key=f"{invoice.id}-{attempt}",
        )
    except (CardDeclinedError, UnavailableError) as exc:
        PlanInvoice.objects.filter(id=invoice.id).update(last_error=str(exc)[:200])
        notices.notify(
            invoice.tenant_id, "card_failed", f"card_failed:{invoice.id}:{attempt}", {"number": invoice.code}
        )
        return False
    if intent.get("status") == "succeeded":
        statements.mark_paid(invoice.id, PROVIDER, intent["id"])
        return True
    return False


# -------------------------------------------------------------- webhooks --


def verify(payload: bytes, header: str, now: float | None = None) -> dict[str, Any]:
    """Stripe's signature: HMAC-SHA256 of `<t>.<payload>` with the endpoint secret, fresh."""
    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        k, _sep, v = item.partition("=")
        parts.setdefault(k.strip(), []).append(v.strip())
    stamp = (parts.get("t") or [""])[0]
    if not secret or not stamp.isdigit():
        msg = _("Unsigned webhook")
        raise InvalidError(msg)
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        msg = _("Bad webhook signature")
        raise InvalidError(msg)
    if abs((now or time.time()) - int(stamp)) > TOLERANCE_SECONDS:
        msg = _("Stale webhook")
        raise InvalidError(msg)
    return json.loads(payload)


def _invoice_of(obj: dict[str, Any]) -> PlanInvoice | None:
    invoice_id = (obj.get("metadata") or {}).get("invoice_id")
    return PlanInvoice.objects.filter(id=invoice_id).first() if invoice_id else None


def _card_saved(obj: dict[str, Any]) -> str:
    if obj.get("mode") != "setup" or not obj.get("setup_intent"):
        return "not a card setup"
    intent = _request("GET", f"/setup_intents/{obj['setup_intent']}")
    sub = TenantSubscription.objects.select_for_update().filter(stripe_customer_id=obj.get("customer")).first()
    if not sub:
        return "unknown customer"
    sub.stripe_payment_method_id = intent["payment_method"]
    sub.payment_method = TenantSubscription.Method.STRIPE
    sub.revision += 1
    sub.save()
    SubscriptionChange.objects.create(
        subscription=sub,
        kind=SubscriptionChange.Kind.SETTINGS,
        effective_at=periods.now(),
        actor_id=PROVIDER,
        actor_name="Stripe",
        detail={"paymentMethod": "stripe"},
    )
    # Anything already owed is charged now that there's a card.
    owed = PlanInvoice.objects.filter(tenant_id=sub.tenant_id, status=PlanInvoice.Status.OPEN).order_by("due_on")
    transaction.on_commit(lambda: [charge(i) for i in owed], robust=True)
    return ""


def _apply(event: dict[str, Any]) -> str:
    """Applies one event; returns why it was skipped ("" when applied)."""
    kind, obj = event.get("type", ""), event.get("data", {}).get("object", {})
    if kind == "checkout.session.completed":
        return _card_saved(obj)
    if kind in {"payment_intent.succeeded", "payment_intent.payment_failed"}:
        invoice = _invoice_of(obj)
        if not invoice:
            return "no invoice"
        if invoice.status != PlanInvoice.Status.OPEN:
            # Out of order or repeated: an invoice only moves forward.
            return f"invoice already {invoice.status}"
        if kind == "payment_intent.succeeded":
            statements.mark_paid(invoice.id, PROVIDER, obj.get("id", ""))
        else:
            error = (obj.get("last_payment_error") or {}).get("message", "declined")
            PlanInvoice.objects.filter(id=invoice.id).update(last_error=str(error)[:200])
        return ""
    return "not handled"


def receive(payload: bytes, header: str) -> str:
    event = verify(payload, header)
    if ProviderEvent.objects.filter(provider=PROVIDER, event_id=str(event.get("id", ""))).exists():
        return "duplicate"
    try:
        with transaction.atomic():
            row = ProviderEvent.objects.create(
                provider=PROVIDER,
                event_id=str(event.get("id", "")),
                type=str(event.get("type", ""))[:80],
                occurred_at=datetime.fromtimestamp(int(event.get("created", time.time())), tz=UTC),
                payload=event,
                status=ProviderEvent.Status.APPLIED,
            )
            skipped = _apply(event)
            if skipped:
                row.status, row.note = ProviderEvent.Status.SKIPPED, skipped[:200]
                row.save(update_fields=["status", "note"])
    except IntegrityError:
        return "duplicate"
    return row.status
