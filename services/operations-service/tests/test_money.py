"""Gap 9 in operations: decimal prices end to end and the tenant's currency on what it raises."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from src.models import Booking, Offering

from .conftest import FITNESS, PRESETS
from .test_operations import Api, ok, setup_desk

if TYPE_CHECKING:
    from .conftest import Calls, Tenant

pytestmark = pytest.mark.django_db(transaction=True)

EUR = {"currency": "EUR", "taxRate": "21.00", "taxLabel": "IVA", "pricesIncludeTax": True}
RENTALS = {
    **FITNESS,
    "presets": [PRESETS["rental"]],
    "resourceTypes": [{**FITNESS["resourceTypes"][1], "label": "Kayak", "attributes": []}],
}


def test_prices_stay_exact_decimals_from_form_to_charge(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token(template=RENTALS, money=EUR))
    # A decimal string a float can't hold exactly; three hours of it must be 36.30, not 36.300000000000004.
    kayak = ok(
        api.post(
            "/offerings",
            {"kind": "rental", "name": "Kayak", "price": "12.10", "requires": [{"type": "asset", "role": "Kayak"}]},
        )
    )
    assert kayak["price"] == "12.10"
    assert Offering.objects.get(id=kayak["id"]).price == Decimal("12.10")
    assert api.post("/offerings", {"kind": "rental", "name": "Bad", "price": "1.234"}).status_code == 422
    ok(api.post("/resources", {"locationId": tenant.site_a, "type": "asset", "name": "K1", "role": "Kayak"}))
    renter = ok(api.post("/customers", {"locationId": tenant.site_a, "name": "Sam Reyes"}))

    start = (datetime.now(tz=UTC) + timedelta(days=1)).date().isoformat()
    body = {"locationId": tenant.site_a, "customerId": renter["id"], "offeringId": kayak["id"], "minutes": 180}
    booked = ok(api.post("/bookings", {**body, "start": f"{start}T10:00"}))
    shown = ok(api.get("/calendar", scope=tenant.site_a, day=start))["board"]["bookings"][0]
    assert (shown["price"], shown["currency"]) == ("36.30", "EUR")
    assert Booking.objects.get(id=booked["id"]).price == Decimal("36.30")

    ok(api.post(f"/bookings/{booked['id']}/status", {"status": "checked_in"}))
    ok(api.post(f"/bookings/{booked['id']}/status", {"status": "completed"}))
    charge = calls.bodies("/internal/charges")[-1]
    assert (charge["amount"], charge["currency"]) == ("36.30", "EUR")
    assert (charge["bookingId"], charge["paid"]) == (booked["id"], False)

    # Charged on return, collected later in billing: the board reads it as paid from then on.
    board = lambda: ok(api.get("/calendar", scope=tenant.site_a, day=start))["board"]["bookings"][0]  # noqa: E731
    assert board()["paid"] is False
    calls.settled = [booked["id"]]
    assert board()["paid"] is True
    calls.down.add("billing.test")
    assert board()["paid"] is False  # billing down: the board still loads

    catalog = ok(api.get("/catalog"))["offerings"]
    assert catalog[0]["offering"]["price"] == "12.10"


def test_balances_from_billing_are_shown_in_the_tenants_currency(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token(money=EUR))
    ids = setup_desk(api, tenant.site_a)
    calls.balances = {ids["member"]: {"spend": "0.10", "balance": "0.20"}}
    listed = ok(api.get("/customers"))
    assert (listed[0]["balance"], listed[0]["spend"]) == ("0.20", "0.10")

    now = datetime.now(tz=UTC)
    Booking.objects.create(
        tenant_id=tenant.id, location_id=tenant.site_a, offering_id=ids["pt"], customer_id=ids["member"],
        start=now - timedelta(minutes=10), end=now + timedelta(minutes=50), status="confirmed", price=90,
    )  # fmt: skip
    today = ok(api.get("/today"))
    alerts = {a["id"]: a for a in today["alerts"]}
    assert alerts["balance"]["detail"] == "€0.20 to collect at the desk"
    assert today["kpis"]["revenue"] == "0.00"
    assert today["arrivals"][0]["price"] == "90.00"
