"""The Tenantly plan (docs/BILLING.md): usage counted once, capped overage, prorated upgrades,
renewals, invoices that reconcile, the payment standing, Stripe, and tenant isolation."""

# Fixtures like `clock` and `identity` are requested for their effect; Stripe secrets are test values.
# ruff: noqa: ARG001, S105, S106, S107

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from django.db import connection
from django.test import Client
from src.models import (
    BillingNotice,
    BillingPeriod,
    EntitlementGrant,
    PlanInvoice,
    PlanVersion,
    TenantSubscription,
    UsageCounter,
    UsageRecord,
)
from src.services import catalog, cycle, periods, standing, statements, stripe, usage

from common.internal import use_transport

from .test_billing import INTERNAL, token

pytestmark = pytest.mark.django_db

NOV = datetime(2026, 11, 1, tzinfo=UTC)
VIEW = ("billing.view",)
MANAGE = ("billing.view", "billing.manage")


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Billing's "now", moved by the test. Starts on 1 November 2026, a 30-day month."""
    c = Clock(NOV)
    monkeypatch.setattr(periods, "now", c)
    return c


@pytest.fixture
def held() -> dict[str, Any]:
    """What identity held before billing owned the plan; a test may change it before first use."""
    return {"plan": "Starter", "terms": None}


@pytest.fixture
def identity(held: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path.endswith("/plan"):
            return httpx.Response(200, json=held)
        return httpx.Response(200, json={"hash": "x"})

    use_transport(httpx.MockTransport(handler))
    yield seen
    use_transport(None)


def auth(ids: dict[str, str], perms: tuple[str, ...] = MANAGE) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token(ids, perms=perms)}"}


def serve(
    client: Client,
    ids: dict[str, str],
    customer: str,
    *,
    ref: str | None = None,
    delta: int = 1,
    at: datetime | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    body = {
        "tenantId": ids["tenant"],
        "metric": "active_customers",
        "subjectKey": customer,
        "label": f"Customer {customer[:4]}",
        "source": "booking.completed" if delta > 0 else "reversal",
        "sourceRef": ref or f"booking:{uuid.uuid4()}",
        "delta": delta,
        "occurredAt": (at or periods.now()).isoformat(),
        "key": key or f"ops-{uuid.uuid4()}",
    }
    response = client.post("/internal/usage", body, content_type="application/json", **INTERNAL)
    assert response.status_code == 200, response.content
    return response.json()


def plan(client: Client, ids: dict[str, str], perms: tuple[str, ...] = MANAGE) -> dict[str, Any]:
    response = client.get("/plan", **auth(ids, perms))
    assert response.status_code == 200, response.content
    return response.json()


def customers(n: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(n)]


# ----------------------------------------------------------------- catalog --


def test_the_public_price_list_and_its_reasoning(clock: Clock) -> None:
    offered = [
        (v.code, v.base_price, v.allowance("active_customers"), v.unit_price("active_customers"), v.overage_cap)
        for v in catalog.offered()
    ]
    assert offered == [
        ("starter", Decimal("29.00"), 75, Decimal("0.40"), Decimal("59.00")),
        ("growth", Decimal("59.00"), 200, Decimal("0.30"), Decimal("129.00")),
        ("enterprise", Decimal("129.00"), 500, Decimal("0.25"), None),
    ]
    for low, high in zip(catalog.offered(), catalog.offered()[1:], strict=False):
        # Each tier's cap is the next tier's price, and is reached before the next tier's
        # allowance: growing on a plan is never dearer than upgrading.
        assert low.overage_cap == high.base_price
        reached = low.allowance("active_customers") + (low.overage_cap - low.base_price) / low.unit_price(
            "active_customers"
        )
        assert reached < high.allowance("active_customers")
    # Offered prices are frozen: a new price is a new version.
    starter = catalog.public("starter")
    starter.base_price = Decimal("19.00")
    with pytest.raises(ValueError, match="publish a new version"):
        starter.save()


# ------------------------------------------------------------------ usage --


def test_each_customer_counts_once_a_period_and_replays_change_nothing(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    ana, ben = customers(2)
    ref = f"booking:{uuid.uuid4()}"
    assert serve(client, ids, ana, ref=ref, key="ops-1") == {"recorded": True}
    assert serve(client, ids, ana, ref=ref, key="ops-1") == {"recorded": False}  # the outbox resent it
    assert serve(client, ids, ana, ref=ref, key="ops-2") == {"recorded": False}  # checked in, then completed
    assert serve(client, ids, ana) == {"recorded": True}  # a second visit: evidence, same count
    serve(client, ids, ben)
    page = plan(client, ids)
    assert (page["usage"]["used"], page["usage"]["allowance"], page["usage"]["remaining"]) == (2, 75, 73)
    assert page["plan"]["name"] == "Starter"
    assert page["estimate"]["total"] == "29.00"
    # The evidence behind the number, with names, in the order they were first served.
    listed = client.get("/plan/customers", **auth(ids, VIEW)).json()
    assert listed["total"] == 2
    assert [c["customerId"] for c in listed["customers"]] == [ana, ben]
    assert listed["customers"][0]["reference"] == ref
    assert UsageRecord.objects.filter(subject_key=ana).count() == 2
    # The subscription came from what identity held, once.
    assert [p for p, _ in identity].count(f"/internal/tenants/{ids['tenant']}/plan") == 1


def test_a_called_off_class_uncounts_only_customers_nothing_else_keeps(
    ids: dict[str, str],
    clock: Clock,
    identity: list[Any],
) -> None:
    client = Client()
    ana, ben = customers(2)
    seat_a, seat_b = f"attendance:{uuid.uuid4()}", f"attendance:{uuid.uuid4()}"
    serve(client, ids, ana, ref=seat_a)
    serve(client, ids, ben, ref=seat_b)
    serve(client, ids, ana)  # Ana also had a PT session
    serve(client, ids, ana, ref=seat_a, delta=-1)
    serve(client, ids, ben, ref=seat_b, delta=-1)
    serve(client, ids, ben, ref=seat_b, delta=-1, key="ops-again")  # reversed once only
    assert plan(client, ids)["usage"]["used"] == 1
    # A reversal of something never counted is evidence only.
    assert serve(client, ids, ben, ref=f"attendance:{uuid.uuid4()}", delta=-1) == {"recorded": True}
    assert plan(client, ids)["usage"]["used"] == 1
    assert periods.reconcile(BillingPeriod.objects.get(status="open")) == []


def test_alerts_fire_once_at_80_and_100_percent(ids: dict[str, str], clock: Clock, identity: list[Any]) -> None:
    client = Client()
    for c in customers(59):
        serve(client, ids, c)
    assert not BillingNotice.objects.exists()
    for c in customers(1):
        serve(client, ids, c)  # 60 of 75 = 80%
    for c in customers(20):
        serve(client, ids, c)  # past 100%
    kinds = list(BillingNotice.objects.order_by("id").values_list("kind", "params__percent"))
    assert kinds == [("threshold", 80), ("threshold", 100)]
    notice = plan(client, ids)["notices"][0]
    assert notice["params"]["overagePrice"] == "0.40"
    assert client.post(f"/plan/notices/{notice['id']}/read", **auth(ids, VIEW)).status_code == 200
    assert plan(client, ids)["notices"][0]["read"] is True


# ----------------------------------------------------------------- pricing --


def test_overage_is_per_customer_and_never_passes_the_next_plans_price(
    ids: dict[str, str],
    clock: Clock,
    identity: list[Any],
) -> None:
    client = Client()
    plan(client, ids)  # a customer since the 1st: a whole month
    clock.at = NOV + timedelta(days=15)
    for c in customers(100):
        serve(client, ids, c)
    page = plan(client, ids)
    assert [(line["kind"], line["amount"]) for line in page["estimate"]["lines"]] == [
        ("base", "29.00"),
        ("overage", "10.00"),
    ]
    assert page["estimate"]["lines"][1]["quantity"] == 25  # 100 - 75, at 0.40
    assert page["estimate"]["total"] == "39.00"
    # Half-way through the month at 100: the pace says 200 by the end, capped at $59.
    assert (page["usage"]["projected"], page["estimate"]["projectedTotal"]) == (200, "59.00")
    # What this period would cost on each plan, to compare with one look.
    assert {p["code"]: p["thisPeriod"] for p in page["plans"]} == {
        "starter": "39.00",
        "growth": "59.00",
        "enterprise": "129.00",
    }

    for c in customers(200):
        serve(client, ids, c)
    capped = plan(client, ids)["estimate"]
    assert [line["kind"] for line in capped["lines"]] == ["base", "overage", "cap"]
    assert (capped["total"], capped["cap"]) == ("59.00", "59.00")
    assert BillingNotice.objects.filter(kind="cap").count() == 1


def test_existing_businesses_keep_their_prices_and_a_custom_plan_is_their_own(
    ids: dict[str, str],
    held: dict[str, Any],
    clock: Clock,
    identity: list[Any],
) -> None:
    client = Client()
    held.update(plan="Growth", since="2025-03-02T10:00:00+00:00")
    page = plan(client, ids)
    assert (page["plan"]["name"], page["plan"]["price"], page["plan"]["included"], page["plan"]["legacy"]) == (
        "Growth",
        "49.00",
        100,
        True,
    )
    # The old cliff (billed as Enterprise past 100) is now 40¢ a customer, capped at that same $89.
    for c in customers(110):
        serve(client, ids, c)
    assert plan(client, ids)["estimate"]["total"] == "53.00"

    other = {**ids, "tenant": str(uuid.uuid4())}
    held.update(plan="Custom", terms={"price": "250.00", "customerLimit": 1_000}, since="2025-01-01T00:00:00+00:00")
    custom = plan(client, other)["plan"]
    assert (custom["name"], custom["price"], custom["included"], custom["custom"]) == ("Custom", "250.00", 1_000, True)
    assert PlanVersion.objects.get(id=custom["id"]).tenant_id == uuid.UUID(other["tenant"])


# ---------------------------------------------------------- plan changes --


def change(
    client: Client, ids: dict[str, str], body: dict[str, Any], key: str | None = None, perms: tuple[str, ...] = MANAGE
) -> Any:
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client.post("/plan/change", body, content_type="application/json", **auth(ids, perms), **headers)


def test_an_upgrade_prorates_now_and_a_downgrade_waits_for_the_renewal(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    revision = plan(client, ids)["revision"]
    clock.at = NOV + timedelta(days=15)
    for c in customers(150):
        serve(client, ids, c)
    up = change(client, ids, {"plan": "growth", "revision": revision}, key="k-up")
    assert up.status_code == 200, up.content
    page = up.json()
    assert page["plan"]["name"] == "Growth"
    # Half a month of each, and 150 customers fit Growth's 200: no overage at all.
    assert [(line["kind"], line["amount"]) for line in page["estimate"]["lines"]] == [
        ("base", "14.50"),
        ("base", "29.50"),
    ]
    # Same key again (a double click): nothing more happens.
    again = change(client, ids, {"plan": "growth", "revision": revision}, key="k-up")
    assert again.json()["revision"] == page["revision"]
    # A stale revision is refused instead of overwriting someone else's change.
    assert change(client, ids, {"plan": "starter", "revision": revision}).status_code == 409

    down = change(client, ids, {"plan": "starter", "revision": page["revision"]}).json()
    assert (down["plan"]["name"], down["scheduled"]["name"]) == ("Growth", "Starter")
    assert ("/internal/audit", "tenantly.downgrade_scheduled") in [(p, b.get("action")) for p, b in identity]

    clock.at = datetime(2026, 12, 1, 1, tzinfo=UTC)
    december = plan(client, ids)
    assert (december["plan"]["name"], december["scheduled"], december["usage"]["used"]) == ("Starter", None, 0)
    kinds = [c["kind"] for c in client.get("/plan/history", **auth(ids, VIEW)).json()["changes"]]
    assert kinds[:3] == ["downgrade_applied", "downgrade_scheduled", "upgrade"]


def test_only_owners_change_the_plan_and_the_client_never_sets_a_price(
    ids: dict[str, str],
    clock: Clock,
    identity: list[Any],
) -> None:
    client = Client()
    revision = plan(client, ids, VIEW)["revision"]
    assert change(client, ids, {"plan": "growth", "revision": revision}, perms=VIEW).status_code == 403
    assert client.get("/plan", **auth(ids, ("payments.collect",))).status_code == 403
    sneaky = change(client, ids, {"plan": "growth", "revision": revision, "price": "1.00"}).json()
    assert sneaky["plan"]["price"] == "59.00"
    assert change(client, ids, {"plan": "custom", "revision": revision + 1}).status_code == 422


def test_the_subscription_is_the_owners_alone(ids: dict[str, str], clock: Clock, identity: list[Any]) -> None:
    """A team member's role carrying `billing.manage` still changes nothing: the team rides on the owner's plan."""
    client = Client()
    revision = plan(client, ids)["revision"]
    staff = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, perms=MANAGE, role='admin')}"}
    page = client.get("/plan", **staff).json()
    assert page["canManage"] is False
    body = {"plan": "growth", "revision": revision}
    assert client.post("/plan/change", body, content_type="application/json", **staff).status_code == 403
    assert client.post(f"/plan/cancel?revision={revision}", **staff).status_code == 403
    assert client.post("/plan/extension", **staff).status_code == 403
    settings = {"spendCap": None, "alertThresholds": [50]}
    assert client.put("/plan/settings", settings, content_type="application/json", **staff).status_code == 403
    assert plan(client, ids)["revision"] == revision


def test_a_plan_that_is_ending_changes_only_after_resuming(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    rev = plan(client, ids)["revision"]
    page = client.post(f"/plan/cancel?revision={rev}", **auth(ids)).json()
    # An upgrade now would be billed and the plan would still end at the renewal.
    refused = change(client, ids, {"plan": "growth", "revision": page["revision"]})
    assert refused.status_code == 422
    assert "resume" in refused.json()["detail"]
    page = client.post(f"/plan/resume?revision={page['revision']}", **auth(ids)).json()
    assert change(client, ids, {"plan": "growth", "revision": page["revision"]}).json()["plan"]["name"] == "Growth"


def test_a_waiting_downgrade_is_withdrawn_even_from_an_older_price_list(
    ids: dict[str, str], held: dict[str, Any], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    held.update(plan="Growth", since="2025-03-02T10:00:00+00:00")
    page = plan(client, ids)
    assert page["plan"]["legacy"] is True
    page = change(client, ids, {"plan": "starter", "revision": page["revision"]}).json()
    assert page["scheduled"]["name"] == "Starter"
    stale = client.post(f"/plan/withdraw?revision={page['revision'] - 1}", **auth(ids))
    assert stale.status_code == 409
    kept = client.post(f"/plan/withdraw?revision={page['revision']}", **auth(ids)).json()
    assert (kept["plan"]["name"], kept["plan"]["legacy"], kept["scheduled"]) == ("Growth", True, None)
    nothing = client.post(f"/plan/withdraw?revision={kept['revision']}", **auth(ids))
    assert nothing.status_code == 422


def test_cancelling_ends_with_the_period_and_can_be_undone(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    rev = plan(client, ids)["revision"]
    page = client.post(f"/plan/cancel?revision={rev}", **auth(ids)).json()
    assert page["cancelAtPeriodEnd"] is True
    page = client.post(f"/plan/resume?revision={page['revision']}", **auth(ids)).json()
    assert page["cancelAtPeriodEnd"] is False
    client.post(f"/plan/cancel?revision={page['revision']}", **auth(ids))
    clock.at = datetime(2026, 12, 1, 1, tzinfo=UTC)
    ended = plan(client, ids)
    assert (ended["status"], ended["standing"]["status"]) == ("canceled", "canceled")
    assert ended["standing"]["retentionUntil"] == "2027-03-01"


def test_spend_cap_and_alerts_are_the_businesss_own(ids: dict[str, str], clock: Clock, identity: list[Any]) -> None:
    client = Client()

    def put(body: dict[str, Any]) -> Any:
        return client.put("/plan/settings", body, content_type="application/json", **auth(ids))

    assert put({"spendCap": "40.00", "alertThresholds": [50]}).status_code == 422  # Starter caps itself at $59
    assert put({"alertThresholds": [0]}).status_code == 422
    assert put({"alertThresholds": [100, 50, 50]}).json()["alertThresholds"] == [50, 100]
    sub = TenantSubscription.objects.get(tenant_id=ids["tenant"])
    sub.plan_version = catalog.public("enterprise")
    sub.save()
    assert put({"spendCap": "100.00"}).status_code == 422  # below Enterprise's price
    page = put({"spendCap": "150.00", "alertThresholds": [90]}).json()
    assert page["spendCap"] == {"editable": True, "value": "150.00", "default": "258.00"}


# ------------------------------------------------------- closing a period --


def close_november(client: Client, ids: dict[str, str], clock: Clock) -> PlanInvoice:
    if clock.at == NOV:
        plan(client, ids)  # subscribed from the 1st
    clock.at = datetime(2026, 12, 4, 1, tzinfo=UTC)
    cycle.run(clock.at)
    return PlanInvoice.objects.get(tenant_id=ids["tenant"])


def test_a_period_is_invoiced_after_its_grace_and_never_changes_after(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    for c in customers(80):
        serve(client, ids, c)
    clock.at = datetime(2026, 12, 1, 0, 30, tzinfo=UTC)
    assert cycle.run(clock.at)["invoiced"] == 0  # November is closing: late usage may still arrive
    late_arrival = customers(1)[0]
    serve(client, ids, late_arrival, at=datetime(2026, 11, 30, 23, tzinfo=UTC))

    invoice = close_november(client, ids, clock)
    assert (invoice.code, invoice.total, invoice.due_on) == ("TNT-000001", Decimal("31.40"), date(2026, 12, 18))
    assert [(line.kind, line.quantity, line.amount) for line in invoice.lines.all()] == [
        ("base", 1, Decimal("29.00")),
        ("overage", 6, Decimal("2.40")),
    ]
    # Too late now: kept as evidence, never billed.
    serve(client, ids, customers(1)[0], at=datetime(2026, 11, 30, 23, 30, tzinfo=UTC))
    assert UsageRecord.objects.filter(late=True).count() == 1
    assert cycle.run(clock.at)["invoiced"] == 0
    assert PlanInvoice.objects.count() == 1
    shown = client.get(f"/plan/invoices/{invoice.id}", **auth(ids, VIEW)).json()
    assert shown["total"] == "31.40"
    assert [h["used"] for h in client.get("/plan/history", **auth(ids, VIEW)).json()["periods"]] == [0, 81]
    assert ("/internal/audit", "tenantly.invoice_paid") not in [(p, b.get("action")) for p, b in identity]


def test_numbers_that_dont_add_up_are_held_not_invoiced(ids: dict[str, str], clock: Clock, identity: list[Any]) -> None:
    client = Client()
    for c in customers(3):
        serve(client, ids, c)
    UsageCounter.objects.filter(metric="active_customers").update(quantity=7)
    clock.at = datetime(2026, 12, 4, 1, tzinfo=UTC)
    cycle.run(clock.at)
    assert not PlanInvoice.objects.exists()
    assert BillingPeriod.objects.get(starts_at=NOV).status == "held"


# --------------------------------------------------------- not paying --


def test_an_unpaid_invoice_escalates_slowly_and_paying_undoes_it(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    invoice = close_november(client, ids, clock)  # $29, due 18 December
    sub = TenantSubscription.objects.get(tenant_id=ids["tenant"])

    def on(day: date) -> str:
        return standing.of(sub, day).status

    assert on(date(2026, 12, 18)) == "active"
    assert on(date(2026, 12, 19)) == "past_due"
    assert on(date(2027, 1, 1)) == "limited"  # 14 days after
    assert on(date(2027, 1, 17)) == "restricted"  # 30 days after

    # One self-serve extension: every date moves a week, once a year.
    clock.at = datetime(2027, 1, 2, 9, tzinfo=UTC)
    page = client.post("/plan/extension", **auth(ids)).json()
    assert page["standing"]["status"] == "past_due"
    assert page["standing"]["limitsOn"] == "2027-01-08"
    assert page["standing"]["extensionAvailable"] is False
    assert client.post("/plan/extension", **auth(ids)).status_code == 422
    sub.refresh_from_db()

    # A dispute stops the escalation while it lasts.
    EntitlementGrant.objects.create(
        tenant_id=sub.tenant_id, kind="dispute", valid_from=clock.at, valid_until=clock.at + timedelta(days=60),
        reason="TNT-000001 under review", approved_by="staff",
    )  # fmt: skip
    assert standing.of(sub, date(2027, 2, 1), clock.at).status == "past_due"
    EntitlementGrant.objects.filter(kind="dispute").delete()

    # Day 45 (+7): the cycle ends the subscription; the data stays, read-only, for 90 days.
    clock.at = datetime(2027, 2, 9, 9, tzinfo=UTC)
    cycle.chase(clock.at.date())
    sub.refresh_from_db()
    assert (sub.status, sub.retention_until) == ("canceled", date(2027, 5, 10))
    assert client.get(f"/internal/tenants/{ids['tenant']}/entitlements", **INTERNAL).json()["status"] == "canceled"
    assert BillingNotice.objects.filter(kind="canceled").count() == 1

    # Paying everything owed brings it all back.
    statements.mark_paid(invoice.id, "manual", "wire #8841")
    statements.mark_paid(invoice.id, "manual", "wire #8841")  # twice: once
    sub.refresh_from_db()
    assert sub.status == "active"
    assert client.get(f"/internal/tenants/{ids['tenant']}/entitlements", **INTERNAL).json()["status"] == "active"
    assert [b["action"] for p, b in identity if p == "/internal/audit"].count("tenantly.invoice_paid") == 1


def test_a_small_balance_never_escalates(ids: dict[str, str], clock: Clock, identity: list[Any]) -> None:
    invoice = close_november(Client(), ids, clock)
    PlanInvoice.objects.filter(id=invoice.id).update(total=Decimal("3.00"))
    sub = TenantSubscription.objects.get(tenant_id=ids["tenant"])
    assert standing.of(sub, date(2027, 3, 1)).status == "past_due"


# ------------------------------------------------------------------ Stripe --


def signed(payload: dict[str, Any], secret: str = "whsec_test", at: int | None = None) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    stamp = str(at or int(time.time()))
    sig = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={stamp},v1={sig}"


def hook(client: Client, payload: dict[str, Any], **kw: Any) -> Any:
    body, header = signed(payload, **kw)
    return client.post("/webhooks/stripe", body, content_type="application/json", HTTP_STRIPE_SIGNATURE=header)


def test_cards_through_stripe_with_verified_deduplicated_webhooks(
    ids: dict[str, str], clock: Clock, identity: list[Any], settings: Any
) -> None:
    settings.STRIPE_SECRET_KEY = "sk_test"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    calls: list[tuple[str, dict[str, str]]] = []
    answers = {"declined": False}

    def api(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode())) if request.content else {}
        calls.append((request.url.path, form))
        if request.url.path == "/v1/customers":
            return httpx.Response(200, json={"id": "cus_1"})
        if request.url.path == "/v1/checkout/sessions":
            return httpx.Response(200, json={"url": "https://checkout.stripe.test/s1"})
        if request.url.path == "/v1/setup_intents/seti_1":
            return httpx.Response(200, json={"id": "seti_1", "payment_method": "pm_1"})
        if answers["declined"]:
            return httpx.Response(402, json={"error": {"message": "Your card was declined."}})
        return httpx.Response(200, json={"id": "pi_1", "status": "succeeded"})

    stripe.use_transport(httpx.MockTransport(api))
    try:
        client = Client()
        plan(client, ids)
        bad_return = {"returnUrl": "https://evil.test/x"}
        assert client.post("/plan/card", bad_return, content_type="application/json", **auth(ids)).status_code == 422
        session = client.post(
            "/plan/card",
            {"returnUrl": "http://localhost:8080/t/x/billing"},
            content_type="application/json",
            **auth(ids),
        )
        assert session.json() == {"url": "https://checkout.stripe.test/s1"}
        saved = {"id": "evt_1", "type": "checkout.session.completed", "created": int(time.time()),
                 "data": {"object": {"mode": "setup", "setup_intent": "seti_1", "customer": "cus_1"}}}  # fmt: skip
        assert hook(client, saved).json() == {"status": "applied"}
        assert hook(client, saved).json() == {"status": "duplicate"}
        assert hook(client, saved, secret="whsec_wrong").status_code == 422
        assert hook(client, {**saved, "id": "evt_old"}, at=int(time.time()) - 3600).status_code == 422
        page = plan(client, ids)
        assert page["payment"] == {"method": "stripe", "card": True, "cardsAvailable": True}

        # Card businesses are charged when the invoice is issued, idempotently per attempt.
        invoice = close_november(client, ids, clock)
        invoice.refresh_from_db()
        assert (invoice.status, invoice.paid_via, invoice.payment_ref) == ("paid", "stripe", "pi_1")
        intent = next(form for path, form in calls if path == "/v1/payment_intents")
        assert (intent["amount"], intent["currency"], intent["metadata[invoice_id]"]) == (
            "2900",
            "usd",
            str(invoice.id),
        )

        # Stripe's own events for it arrive afterwards, and out of order: nothing moves back.
        failed = {"id": "evt_2", "type": "payment_intent.payment_failed", "created": int(time.time()),
                  "data": {"object": {"id": "pi_1", "metadata": {"invoice_id": str(invoice.id)}}}}  # fmt: skip
        assert hook(client, failed).json() == {"status": "skipped"}
        invoice.refresh_from_db()
        assert invoice.status == "paid"

        # A declined card leaves the invoice open, says so, and the cycle tries again on day 3.
        answers["declined"] = True
        clock.at = datetime(2027, 1, 4, 1, tzinfo=UTC)
        cycle.run(clock.at)
        december = PlanInvoice.objects.exclude(id=invoice.id).get(tenant_id=ids["tenant"])
        assert (december.status, december.attempts, december.last_error) == ("open", 1, "Your card was declined.")
        assert BillingNotice.objects.filter(kind="card_failed").exists()
        clock.at = datetime(2027, 1, 7, 9, tzinfo=UTC)
        answers["declined"] = False
        cycle.chase(clock.at.date())
        december.refresh_from_db()
        assert (december.status, december.attempts) == ("paid", 2)
    finally:
        stripe.use_transport(None)


# --------------------------------------------------------------- isolation --


def test_a_business_sees_only_its_own_plan_usage_and_invoices(
    ids: dict[str, str],
    clock: Clock,
    identity: list[Any],
) -> None:
    client = Client()
    serve(client, ids, customers(1)[0])
    invoice = close_november(client, ids, clock)
    other = {**ids, "tenant": str(uuid.uuid4())}
    assert client.get(f"/plan/invoices/{invoice.id}", **auth(other, VIEW)).status_code == 404
    assert plan(client, other)["usage"]["used"] == 0
    assert client.get("/plan/customers", **auth(other, VIEW)).json()["total"] == 0
    # Usage only arrives from inside: not with a tenant token, not without the internal one.
    body = {"tenantId": ids["tenant"], "metric": "active_customers", "subjectKey": "x", "source": "s",
            "sourceRef": "r", "occurredAt": clock.at.isoformat(), "key": "k"}  # fmt: skip
    assert client.post("/internal/usage", body, content_type="application/json", **auth(ids)).status_code == 401
    assert client.post("/internal/usage", body, content_type="application/json").status_code == 401


# ------------------------------------------------------------- concurrency --


@pytest.mark.django_db(transaction=True)
def test_concurrent_events_count_each_customer_once(ids: dict[str, str], clock: Clock, identity: list[Any]) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("row locks need Postgres: DATABASE_URL=postgres://… pytest")
    from django.apps import apps  # noqa: PLC0415
    from src.schemas import UsageIn  # noqa: PLC0415

    # Transactional tests flush what data migrations seeded: put the catalog back.
    importlib.import_module("src.migrations.0005_seed_plan_versions").forward(apps, None)
    seed = {"tenantId": ids["tenant"], "metric": "active_customers", "subjectKey": "seed", "source": "s",
            "sourceRef": "seed", "occurredAt": NOV.isoformat(), "key": "seed"}  # fmt: skip
    usage.record(UsageIn.model_validate(seed))
    ana = str(uuid.uuid4())
    others = customers(70)
    errors: list[BaseException] = []

    def send(subject: str, ref: str) -> None:
        try:
            body = {"tenantId": ids["tenant"], "metric": "active_customers", "subjectKey": subject, "source": "s",
                    "sourceRef": ref, "occurredAt": NOV.isoformat(), "key": f"ops-{uuid.uuid4()}"}  # fmt: skip
            usage.record(UsageIn.model_validate(body))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    jobs = [(ana, f"booking:{i}") for i in range(10)] + [(c, f"booking:{c}") for c in others]
    threads = [threading.Thread(target=send, args=job) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    period = BillingPeriod.objects.get(tenant_id=ids["tenant"], status="open")
    assert usage.used(period) == 72  # seed + Ana once + 70 others
    assert BillingNotice.objects.filter(kind="threshold", params__percent=80).count() == 1
    assert periods.reconcile(period) == []
