"""Payment-provider webhooks: public (the proxy forwards them), authenticated by signature."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ninja import Router

from ..services import stripe

if TYPE_CHECKING:
    from django.http import HttpRequest

router = Router(tags=["webhooks"])


@router.post("/stripe")
def stripe_webhook(request: HttpRequest) -> dict[str, str]:
    return {"status": stripe.receive(request.body, request.headers.get("Stripe-Signature", ""))}
