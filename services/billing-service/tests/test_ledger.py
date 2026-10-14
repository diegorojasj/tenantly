"""The business ledger: expenses and other income beside the charges."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.test import Client

from .test_billing import INTERNAL, TODAY, audits, charge, token

pytestmark = pytest.mark.django_db

__all__ = ["audits"]


def entry(client: Client, ids: dict[str, str], **over: Any) -> dict[str, Any]:
    body = {
        "tenantId": ids["tenant"],
        "locationId": ids["a"],
        "kind": "expense",
        "category": "repair",
        "description": "Plumber",
        "amount": "420.50",
        "date": TODAY.isoformat(),
        **over,
    }
    response = client.post("/internal/entries", body, content_type="application/json", **INTERNAL)
    assert response.status_code == 200, response.content
    return response.json()


def test_downtime_lines_are_idempotent_and_read_back_per_downtime(ids: dict[str, str]) -> None:
    client = Client()
    down, other = str(uuid.uuid4()), str(uuid.uuid4())
    first = entry(client, ids, refId=down, key="ops-1")
    assert entry(client, ids, refId=down, key="ops-1") == first
    entry(client, ids, refId=down, kind="income", category="insurance", amount="300.00", key="ops-2")
    entry(client, ids, refId=down, kind="income", amount="80.00", charged=True, key="ops-3")
    entry(client, ids, refId=other, amount="10.00", key="ops-4")

    answer = client.post(
        "/internal/entries/by-ref",
        {"tenantId": ids["tenant"], "refIds": [down]},
        content_type="application/json",
        **INTERNAL,
    ).json()
    assert list(answer) == [down]
    assert answer[down]["expense"] == "420.50"
    assert answer[down]["income"] == "380.00"
    assert len(answer[down]["entries"]) == 3
    assert client.post("/internal/entries", {}, content_type="application/json").status_code == 401


def test_the_ledger_nets_revenue_income_and_expenses(ids: dict[str, str], audits: list[dict[str, Any]]) -> None:
    client = Client()
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token(ids)}"}
    charge(client, ids, amount="200.00", paid=True)
    refunded = charge(client, ids, amount="50.00", paid=True)
    client.post(f"/charges/{refunded}/refund", **auth)
    entry(client, ids, refId=str(uuid.uuid4()))
    entry(client, ids, kind="income", category="insurance", amount="100.00")
    # Charged to a customer: listed, but the charge already counts it.
    entry(client, ids, kind="income", amount="80.00", charged=True)
    entry(client, ids, locationId=ids["b"], amount="999.00")

    rent = client.post(
        "/ledger",
        {"locationId": ids["a"], "kind": "expense", "category": "Rent", "amount": "1000"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="k1",
        **auth,
    )
    assert rent.status_code == 200, rent.content
    assert rent.json()["source"] == "manual"
    assert rent.json()["description"] == "Rent"
    again = client.post(
        "/ledger",
        {"locationId": ids["a"], "kind": "expense", "category": "Rent", "amount": "1000"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="k1",
        **auth,
    )
    assert again.json()["id"] == rent.json()["id"]
    assert audits[-1]["action"] == "ledger.expense"

    book = client.get("/ledger", {"scope": ids["a"]}, **auth).json()
    assert book["totals"] == {"revenue": "200.00", "income": "100.00", "expense": "1420.50", "net": "-1120.50"}
    assert book["byCategory"][0] == {"kind": "expense", "category": "Rent", "amount": "1000.00"}
    assert len(book["entries"]) == 4
    assert book["canRecord"] is True

    void = client.post(f"/ledger/{rent.json()['id']}/void", **auth)
    assert void.json()["voided"] is True
    assert client.post(f"/ledger/{rent.json()['id']}/void", **auth).status_code == 422
    assert client.get("/ledger", {"scope": ids["a"]}, **auth).json()["totals"]["expense"] == "420.50"
    assert client.get("/ledger", **auth).json()["totals"]["expense"] == "1419.50"


def test_only_collectors_record_and_scope_is_kept(ids: dict[str, str], audits: list[dict[str, Any]]) -> None:  # noqa: ARG001
    client = Client()
    away = entry(client, ids, locationId=ids["b"])
    desk = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, home=ids['a'])}"}
    assert client.post(f"/ledger/{away['id']}/void", **desk).status_code == 404
    assert client.get("/ledger", {"scope": ids["b"]}, **desk).json()["entries"] == []
    viewer = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, perms=('analytics.view',))}"}
    assert client.get("/ledger", **viewer).json()["canRecord"] is False
    refused = client.post(
        "/ledger",
        {"locationId": ids["a"], "kind": "expense", "category": "Rent", "amount": "10"},
        content_type="application/json",
        **viewer,
    )
    assert refused.status_code == 403
    nobody = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, perms=('bookings.manage',))}"}
    assert client.get("/ledger", **nobody).status_code == 403
