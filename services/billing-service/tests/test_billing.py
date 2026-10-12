"""Billing: raising, collecting, refunding, overdue, revenue, scope."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from django.test import Client

from common.auth import Node, TenantClaims, issue
from common.internal import use_transport

pytestmark = pytest.mark.django_db
INTERNAL = {"HTTP_X_INTERNAL_TOKEN": "test-internal-token"}
TODAY = datetime.now(tz=UTC).date()


@pytest.fixture
def audits() -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"hash": "x"})

    use_transport(httpx.MockTransport(handler))
    yield seen
    use_transport(None)


def token(
    ids: dict[str, str],
    home: str | None = None,
    perms: tuple[str, ...] = ("payments.collect", "analytics.view", "bookings.manage"),
    money: dict[str, Any] | None = None,
    role: str = "owner",
) -> str:
    return issue(
        TenantClaims(
            user_id="u1",
            user_name="Ana",
            tenant_id=ids["tenant"],
            tenant_slug="x",
            template_id="fitness",
            role=role,
            permissions=perms,
            home_scope_id=home or ids["org"],
            nodes=(
                Node(ids["org"], None, "org", "Biz"),
                Node(ids["a"], ids["org"], "location", "A"),
                Node(ids["b"], ids["org"], "location", "B"),
            ),
            money=money or {},
        )
    )


def charge(client: Client, ids: dict[str, str], **over: Any) -> str:
    body = {
        "tenantId": ids["tenant"],
        "locationId": ids["a"],
        "customerId": ids["customer"],
        "customerName": "Lena",
        "description": "Personal training",
        "source": "booking",
        "amount": "90.00",
        "date": TODAY.isoformat(),
        "paid": False,
        **over,
    }
    response = client.post("/internal/charges", body, content_type="application/json", **INTERNAL)
    assert response.status_code == 200, response.content
    return response.json()["id"]


def test_internal_routes_need_the_internal_token(ids: dict[str, str]) -> None:
    response = Client().post("/internal/charges", {}, content_type="application/json")
    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in to continue"
    assert ids


def test_a_retried_charge_is_raised_once(ids: dict[str, str]) -> None:
    client = Client()
    first = charge(client, ids, key="ops-1")
    assert charge(client, ids, key="ops-1") == first
    assert charge(client, ids, key="ops-2") != first


def test_collect_moves_money_from_due_to_collected(ids: dict[str, str], audits: list[dict[str, Any]]) -> None:
    client = Client()
    owed = charge(client, ids)
    charge(client, ids, amount="40.00", date=(TODAY - timedelta(days=20)).isoformat())
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token(ids)}"}
    before = client.get("/payments", **auth).json()["summary"]
    assert before == {"collected30": "0.00", "due": "90.00", "overdue": "40.00", "refunded30": "0.00"}
    collected = client.post(f"/charges/{owed}/collect", **auth).json()
    assert collected["status"] == "paid"
    after = client.get("/payments", **auth).json()["summary"]
    assert after["collected30"] == "90.00"
    assert after["due"] == "0.00"
    assert audits[-1]["action"] == "charge.collected"
    again = client.post(f"/charges/{owed}/collect", **auth)
    assert again.status_code == 422


def test_errors_answer_in_the_request_language(ids: dict[str, str]) -> None:
    client = Client()
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token(ids)}"}
    missing = client.post(f"/charges/{uuid.uuid4()}/collect", HTTP_ACCEPT_LANGUAGE="es", **auth)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Ese cargo está fuera de tu alcance"


def test_cancelling_a_booking_refunds_paid_and_drops_owed(ids: dict[str, str]) -> None:
    client = Client()
    booking = str(uuid.uuid4())
    charge(client, ids, bookingId=booking, paid=True, source="dropin")
    charge(client, ids, bookingId=booking, source="fee", amount="10.00")
    response = client.post(
        f"/internal/bookings/{booking}/refund", {"tenantId": ids["tenant"]}, content_type="application/json", **INTERNAL
    )
    assert response.json() == {"refunded": 1}
    balances = client.post(
        "/internal/balances", {"tenantId": ids["tenant"]}, content_type="application/json", **INTERNAL
    ).json()
    assert balances == {}


def test_a_bookings_charges_and_when_it_is_settled(ids: dict[str, str], audits: list[dict[str, Any]]) -> None:
    client = Client()
    rental, fee_only, prepaid = (str(uuid.uuid4()) for _ in range(3))
    owed = charge(client, ids, bookingId=rental)
    charge(client, ids, bookingId=fee_only, source="fee", amount="10.00")
    charge(client, ids, bookingId=prepaid, paid=True)
    settled = lambda: client.post(  # noqa: E731
        "/internal/bookings/settled",
        {"tenantId": ids["tenant"], "bookingIds": [rental, fee_only, prepaid]},
        content_type="application/json",
        **INTERNAL,
    ).json()
    assert settled() == [prepaid]

    auth = {"HTTP_AUTHORIZATION": f"Bearer {token(ids)}"}
    seen = client.get(f"/bookings/{rental}/charges", **auth).json()
    assert seen["canCollect"] is True
    assert [(c["id"], c["bookingId"], c["status"]) for c in seen["charges"]] == [(owed, rental, "due")]
    client.post(f"/charges/{owed}/collect", **auth)
    assert audits[-1]["action"] == "charge.collected"
    assert sorted(settled()) == sorted([rental, prepaid])

    desk = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, perms=('bookings.manage',))}"}
    assert client.get(f"/bookings/{rental}/charges", **desk).json()["canCollect"] is False
    other_site = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, home=ids['b'])}"}
    assert client.get(f"/bookings/{rental}/charges", **other_site).json()["charges"] == []
    nobody = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, perms=('audit.view',))}"}
    assert client.get(f"/bookings/{rental}/charges", **nobody).json() == {"canSee": False, "canCollect": False, "charges": []}


def test_revenue_and_scope(ids: dict[str, str]) -> None:
    client = Client()
    charge(client, ids, paid=True)
    charge(client, ids, locationId=ids["b"], amount="10.00", paid=True)
    split = client.post(
        "/internal/revenue",
        {
            "tenantId": ids["tenant"],
            "locationIds": [ids["a"], ids["b"]],
            "start": TODAY.isoformat(),
            "end": TODAY.isoformat(),
        },
        content_type="application/json",
        **INTERNAL,
    ).json()
    assert split["byDay"] == {TODAY.isoformat(): "100.00"}
    assert split["byLocation"] == {ids["a"]: "90.00", ids["b"]: "10.00"}
    site_b = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, home=ids['b'])}"}
    seen = client.get("/payments", **site_b).json()["charges"]
    assert [c["amount"] for c in seen] == ["10.00"]
    refused = client.get("/payments", HTTP_AUTHORIZATION=f"Bearer {token(ids, perms=('audit.view',))}")
    assert refused.status_code == 403
