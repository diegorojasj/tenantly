"""Gap 9 in billing: decimal amounts, currency snapshots, customer invoices with tax."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client

from common.internal import use_transport
from common.money import label, tax_split

from .test_billing import INTERNAL, TODAY, charge, token

pytestmark = pytest.mark.django_db

EUR_VAT = {"currency": "EUR", "taxRate": "21.00", "taxLabel": "VAT", "pricesIncludeTax": False}


@pytest.fixture
def held() -> dict[str, Any]:
    """The plan identity answers with; a test may change it."""
    return {"plan": "Starter", "terms": None}


@pytest.fixture
def services(held: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Identity, mocked: audit appends and the plan lookup."""
    seen: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path.endswith("/plan"):
            return httpx.Response(200, json=held)
        return httpx.Response(200, json={"hash": "x"})

    use_transport(httpx.MockTransport(handler))
    yield seen
    use_transport(None)


def test_tax_split_rounds_to_the_cent_both_ways() -> None:
    assert tax_split(Decimal("121.00"), Decimal("21"), inclusive=True) == (
        Decimal("100.00"),
        Decimal("21.00"),
        Decimal("121.00"),
    )
    assert tax_split(Decimal("10.00"), Decimal("7.25"), inclusive=False) == (
        Decimal("10.00"),
        Decimal("0.73"),
        Decimal("10.73"),
    )
    assert tax_split(Decimal("0.10"), Decimal("0"), inclusive=True)[1] == Decimal("0.00")
    assert label("1234.5", "EUR") == "€1,234.50"
    assert label("3", "CHF") == "CHF 3.00"


def test_an_invoice_gathers_open_charges_adds_tax_and_collects_them(
    ids: dict[str, str], services: list[tuple[str, dict[str, Any]]]
) -> None:
    client = Client()
    first = charge(client, ids, amount="0.10", currency="EUR")
    charge(client, ids, amount="0.20", currency="EUR", locationId=ids["b"])
    charge(client, ids, amount="5.00", currency="EUR", paid=True)  # already paid: not invoiced
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, money=EUR_VAT)}"}

    issued = client.post("/invoices", {"customerId": ids["customer"]}, content_type="application/json", **auth)
    assert issued.status_code == 200, issued.content
    inv = issued.json()
    # 0.10 + 0.20 is exactly 0.30: no float drift anywhere on the way.
    assert (inv["number"], inv["currency"], inv["subtotal"], inv["tax"], inv["total"]) == (
        "INV-0001",
        "EUR",
        "0.30",
        "0.06",
        "0.36",
    )
    assert (inv["taxLabel"], inv["taxRate"], inv["status"]) == ("VAT", "21.00", "open")
    assert [line["amount"] for line in inv["lines"]] == ["0.10", "0.20"]
    assert services[-1][1]["action"] == "invoice.issued"
    assert "€0.36" in services[-1][1]["target"]

    # Invoiced charges are collected through their invoice, not one by one.
    assert client.post(f"/charges/{first}/collect", **auth).status_code == 422
    again = client.post("/invoices", {"customerId": ids["customer"]}, content_type="application/json", **auth)
    assert again.status_code == 422

    paid = client.post(f"/invoices/{inv['id']}/pay", **auth).json()
    assert (paid["status"], paid["paidOn"]) == ("paid", TODAY.isoformat())
    summary = client.get("/payments", **auth).json()
    assert summary["currency"] == "EUR"
    assert summary["summary"]["due"] == "0.00"
    assert summary["summary"]["collected30"] == "5.30"
    assert client.post(f"/invoices/{inv['id']}/void", **auth).status_code == 422
    listed = client.get("/invoices", **auth).json()
    assert [i["number"] for i in listed["invoices"]] == ["INV-0001"]
    assert listed["canIssue"] is True


def test_prices_with_tax_inside_show_its_share_and_voiding_releases_charges(
    ids: dict[str, str],
    services: list[tuple[str, dict[str, Any]]],  # noqa: ARG001 - identity, mocked
) -> None:
    client = Client()
    booking = str(uuid.uuid4())
    charge(client, ids, amount="121.00", bookingId=booking)
    charge(client, ids, amount="10.00")
    inclusive = {**EUR_VAT, "currency": "USD", "pricesIncludeTax": True}
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, money=inclusive)}"}
    inv = client.post("/invoices", {"customerId": ids["customer"]}, content_type="application/json", **auth).json()
    assert (inv["subtotal"], inv["tax"], inv["total"]) == ("108.26", "22.74", "131.00")

    # Cancelling the booking drops its owed charge; the open invoice is totalled again.
    client.post(
        f"/internal/bookings/{booking}/refund", {"tenantId": ids["tenant"]}, content_type="application/json", **INTERNAL
    )
    again = client.get(f"/invoices/{inv['id']}", **auth).json()
    assert (again["total"], len(again["lines"])) == ("10.00", 1)

    voided = client.post(f"/invoices/{inv['id']}/void", **auth).json()
    assert voided["status"] == "void"
    second = client.post("/invoices", {"customerId": ids["customer"]}, content_type="application/json", **auth).json()
    assert (second["number"], second["total"]) == ("INV-0002", "10.00")

    # Scope and permissions: another site's member can't see it, an auditor can't issue.
    site_b = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, home=ids['b'], money=inclusive)}"}
    assert client.get(f"/invoices/{second['id']}", **site_b).status_code == 404
    reader = {"HTTP_AUTHORIZATION": f"Bearer {token(ids, perms=('analytics.view',))}"}
    assert (
        client.post("/invoices", {"customerId": ids["customer"]}, content_type="application/json", **reader).status_code
        == 403
    )


@pytest.mark.django_db(transaction=True)
def test_currency_and_invoice_migration_is_reversible(ids: dict[str, str]) -> None:
    before = [("billing", "0002_charge_key")]
    after = [("billing", "0003_currency_invoices")]

    def migrate(target: list[tuple[str, str]]) -> Any:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps.get_model("billing", "Charge")

    old = migrate(before)
    old.objects.create(
        tenant_id=ids["tenant"],
        location_id=ids["a"],
        customer_id=ids["customer"],
        customer_name="Lena",
        description="Spin",
        source="booking",
        amount=Decimal("12.50"),
        date=TODAY,
        status="due",
    )
    new = migrate(after)
    row = new.objects.get()
    assert (row.currency, row.amount, row.invoice_id) == ("USD", Decimal("12.50"), None)
    assert migrate(before).objects.get().amount == Decimal("12.50")
    # Leave the schema as the next tests expect it: fully migrated.
    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes("billing"))
