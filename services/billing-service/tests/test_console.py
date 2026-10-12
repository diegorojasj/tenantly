"""What the Tenantly admin console reads and does through billing's internal routes: summaries
in one batch, a business's subscription in detail, grants and manual payments signed by the
admin, and never a subscription created behind identity's back."""

# Fixtures like `clock` and `identity` are requested for their effect.
# ruff: noqa: ARG001

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from django.core.management import call_command
from django.test import Client
from src.models import EntitlementGrant, TenantSubscription
from src.services import cycle, periods

from common.internal import use_transport

from .test_billing import INTERNAL
from .test_plans import NOV, Clock, customers, plan, serve

pytestmark = pytest.mark.django_db

ADMIN = {"id": "u-admin", "name": "Dana (Tenantly)"}


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock(NOV)
    monkeypatch.setattr(periods, "now", c)
    return c


@pytest.fixture
def identity() -> list[tuple[str, dict[str, Any]]]:
    """Identity as billing sees it: the plan it held (Starter) and the audit trail."""
    seen: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path.endswith("/plan"):
            return httpx.Response(200, json={"plan": "Starter", "terms": None})
        return httpx.Response(200, json={"hash": "x"})

    use_transport(httpx.MockTransport(handler))
    yield seen
    use_transport(None)


def internal(client: Client, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    send = getattr(client, method)
    if body is None:
        return send(path, **INTERNAL)
    return send(path, body, content_type="application/json", **INTERNAL)


def test_summaries_come_in_one_batch_and_skip_businesses_without_a_subscription(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    for c in customers(3):
        serve(client, ids, c)
    stranger = str(uuid.uuid4())
    path = "/internal/admin/summaries"
    assert client.post(path, {"tenantIds": [ids["tenant"]]}, content_type="application/json").status_code == 401
    got = internal(client, "post", path, {"tenantIds": [ids["tenant"], stranger]})
    assert got.status_code == 200, got.content
    assert got.json() == {
        ids["tenant"]: {
            "plan": "Starter",
            "currency": "USD",
            "price": "29.00",
            "status": "active",
            "used": 3,
            "allowance": 75,
            "periodEnd": "2026-12-01T00:00:00+00:00",
            "openBalance": "0.00",
        }
    }
    # Reading never creates a subscription (nor asks identity for one).
    assert not TenantSubscription.objects.filter(tenant_id=stranger).exists()
    assert internal(client, "post", path, {"tenantIds": ["not-a-uuid"]}).status_code == 422


def test_detail_shows_plan_usage_invoices_grants_and_history(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    for c in customers(80):
        serve(client, ids, c)
    clock.at = datetime(2026, 12, 4, 1, tzinfo=UTC)
    cycle.run(clock.at)  # November is invoiced: $29 + 5 x $0.40
    path = f"/internal/tenants/{ids['tenant']}/subscription"
    detail = internal(client, "get", path).json()
    assert (detail["plan"]["name"], detail["status"], detail["standing"]["status"]) == ("Starter", "active", "active")
    assert detail["period"]["start"] == "2026-12-01T00:00:00+00:00"
    assert detail["usage"] == {"used": 0, "allowance": 75, "projected": None}
    assert detail["estimate"]["total"] == "29.00"
    assert [(i["number"], i["total"], i["status"]) for i in detail["invoices"]] == [("TNT-000001", "31.00", "open")]
    assert [c["kind"] for c in detail["changes"]] == ["created"]
    assert [p["code"] for p in detail["plans"]] == ["starter", "growth", "enterprise"]
    assert detail["grants"] == []

    # Unknown, malformed, or simply not subscribed yet: a 404, and nothing created.
    for other in (str(uuid.uuid4()), "nope"):
        missing = internal(client, "get", f"/internal/tenants/{other}/subscription")
        assert missing.status_code == 404
        assert missing.json()["code"] == "not_found"
    assert TenantSubscription.objects.count() == 1


def test_grants_are_bounded_signed_by_the_admin_and_audited(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    plan(client, ids)
    path = f"/internal/tenants/{ids['tenant']}/grants"
    body = {
        "kind": "extra_allowance",
        "metric": "active_customers",
        "value": "25",
        "days": 31,
        "reason": "launch week",
        "actor": ADMIN,
    }
    made = internal(client, "post", path, body)
    assert made.status_code == 200, made.content
    assert (made.json()["kind"], made.json()["value"], made.json()["approvedBy"]) == (
        "extra_allowance",
        "25.00",
        "Dana (Tenantly)",
    )
    assert made.json()["validUntil"] == "2026-12-02T00:00:00+00:00"
    audit = [b for p, b in identity if p == "/internal/audit"][-1]
    assert (audit["action"], audit["actorId"], audit["actorName"], audit["category"]) == (
        "tenantly.grant",
        "u-admin",
        "Dana (Tenantly)",
        "billing",
    )
    detail = internal(client, "get", f"/internal/tenants/{ids['tenant']}/subscription").json()
    assert detail["usage"]["allowance"] == 100
    assert [g["reason"] for g in detail["grants"]] == ["launch week"]

    # Extra allowance names its metric; discounts stay within 100%; a reason is required.
    assert internal(client, "post", path, {**body, "metric": ""}).status_code == 422
    assert internal(client, "post", path, {**body, "kind": "discount_pct", "value": "120"}).status_code == 422
    assert internal(client, "post", path, {**body, "reason": ""}).status_code == 422
    stranger = f"/internal/tenants/{uuid.uuid4()}/grants"
    assert internal(client, "post", stranger, body).status_code == 404
    assert EntitlementGrant.objects.count() == 1

    # The CLI goes through the same rules.
    out = io.StringIO()
    call_command("grant", ids["tenant"], "dispute", "--days", "14", "--reason", "TNT-1 under review", stdout=out)
    assert "dispute" in out.getvalue()
    assert EntitlementGrant.objects.get(kind="dispute").approved_by == "Tenantly staff"


def test_marking_an_invoice_paid_is_signed_and_idempotent(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    plan(client, ids)
    clock.at = datetime(2026, 12, 4, 1, tzinfo=UTC)
    cycle.run(clock.at)
    invoice = internal(client, "get", f"/internal/tenants/{ids['tenant']}/subscription").json()["invoices"][0]
    path = f"/internal/plan-invoices/{invoice['id']}/paid"
    body = {"reference": "wire #8841", "actor": ADMIN}
    first = internal(client, "post", path, body)
    assert first.status_code == 200, first.content
    assert (first.json()["status"], first.json()["paidVia"]) == ("paid", "manual")
    assert first.json()["before"] == {"status": "open"}  # for the admin audit log
    again = internal(client, "post", path, body)
    assert {**again.json(), "before": None} == {**first.json(), "before": None}
    assert again.json()["before"] == {"status": "paid"}
    paid = [b for p, b in identity if p == "/internal/audit" and b["action"] == "tenantly.invoice_paid"]
    assert [(b["actorId"], b["actorName"]) for b in paid] == [("u-admin", "Dana (Tenantly)")]

    assert internal(client, "post", path, {"reference": ""}).status_code == 422
    assert internal(client, "post", f"/internal/plan-invoices/{uuid.uuid4()}/paid", body).status_code == 404
    assert internal(client, "post", "/internal/plan-invoices/nope/paid", body).status_code == 404


def test_the_admin_assigns_a_plan_and_history_names_them(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    plan(client, ids)
    path = f"/internal/tenants/{ids['tenant']}/plan"
    body = {
        "plan": "custom",
        "terms": {"price": "250.00", "customerLimit": 1000, "overagePrice": "0.20"},
        "reason": "3-year deal",
        "actor": ADMIN,
    }
    done = internal(client, "put", path, body)
    assert done.json() == {
        "plan": "Custom",
        "status": "active",
        "before": {"plan": "Starter", "version": 2, "status": "active"},  # for the admin audit log
    }
    change = internal(client, "get", f"/internal/tenants/{ids['tenant']}/subscription").json()["changes"][0]
    assert (change["kind"], change["by"], change["detail"]) == (
        "assigned",
        "Dana (Tenantly)",
        {"reason": "3-year deal"},
    )
    audit = [b for p, b in identity if p == "/internal/audit"][-1]
    assert (audit["action"], audit["actorName"]) == ("tenantly.plan_assigned", "Dana (Tenantly)")
    # The CLI's body has no actor: signed "Tenantly", as before.
    internal(client, "put", path, {"plan": "growth"})
    assert internal(client, "get", f"/internal/tenants/{ids['tenant']}/subscription").json()["changes"][0]["by"] == (
        "Tenantly"
    )

    # A business with no subscription yet starts on the assigned plan, without asking identity.
    fresh = str(uuid.uuid4())
    before = len(identity)
    assert internal(
        client, "put", f"/internal/tenants/{fresh}/plan", {**body, "plan": "growth", "terms": None}
    ).json() == {
        "plan": "Growth",
        "status": "active",
        "before": None,
    }
    assert [p for p, _ in identity[before:]] == ["/internal/audit"]
    created = internal(client, "get", f"/internal/tenants/{fresh}/subscription").json()
    assert (created["changes"][0]["kind"], created["changes"][0]["by"]) == ("created", "Dana (Tenantly)")
