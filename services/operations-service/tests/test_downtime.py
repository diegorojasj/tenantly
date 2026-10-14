"""Downtime: repairs, maintenance, absences and closures take things out of booking, and carry money."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from .conftest import FITNESS, PRESETS
from .test_fulfilment import add
from .test_operations import TOMORROW, Api, ok, setup_desk

if TYPE_CHECKING:
    from .conftest import Calls, Tenant

pytestmark = pytest.mark.django_db(transaction=True)

DAY_AFTER = (datetime.now(tz=UTC) + timedelta(days=2)).date().isoformat()


def book(api: Api, site: str, ids: dict[str, str], start: str) -> dict[str, Any]:
    body = {"locationId": site, "offeringId": ids["pt"], "customerId": ids["member"], "staffId": ids["coach"]}
    return api.post("/bookings", {**body, "start": start})


def slots(api: Api, site: str, ids: dict[str, str], day: str = TOMORROW) -> dict[str, Any]:
    return ok(api.get("/availability", location=site, offering=ids["pt"], staff=ids["coach"], day=day))


def test_a_resource_down_is_never_offered_and_its_bookings_are_flagged(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token())
    site = tenant.site_a
    ids = setup_desk(api, site)
    kept = ok(book(api, site, ids, f"{TOMORROW}T10:00"))

    ok(
        api.post(
            "/downtimes",
            {
                "resourceId": ids["coach"],
                "reason": "absence",
                "note": "Sick leave",
                "start": f"{TOMORROW}T09:00",
                "end": f"{TOMORROW}T12:00",
            },
        )
    )
    free = slots(api, site, ids)["slots"]
    assert "08:00" in free
    assert not {"09:00", "10:00", "11:00", "11:30"} & set(free)
    assert "12:00" in free
    refused = book(api, site, ids, f"{TOMORROW}T11:00")
    assert refused.status_code == 409
    assert "Omar is unavailable" in refused.json()["detail"]
    assert "absence" in refused.json()["detail"]

    # The booking made before stays, flagged for the desk, and Today raises it.
    [row] = ok(api.get("/bookings", range="upcoming"))["bookings"]
    assert row["id"] == kept["id"]
    assert row["downtime"] == {"id": row["downtime"]["id"], "reason": "absence", "what": "Omar", "target": "resource"}
    alert = next(a for a in ok(api.get("/today"))["alerts"] if a["id"] == "clashes")
    assert alert["tone"] == "bad"
    assert "Omar · absence" in alert["detail"]

    listing = ok(api.get("/downtimes"))
    [down] = listing["downtimes"]
    assert down["state"] == "upcoming"
    assert [c["id"] for c in down["clashes"]] == [kept["id"]]
    assert down["money"] == {"income": "0.00", "expense": "0.00", "entries": []}


def test_cancelling_a_booking_a_downtime_put_in_doubt_waives_the_late_fee(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    site = tenant.site_a
    ids = setup_desk(api, site)
    ok(api.put("/policies", {"scope": site, "key": "booking.cancelHours", "value": 48}))
    ok(api.put("/policies", {"scope": site, "key": "payments.noShowFee", "value": "50% of price"}))
    first = ok(book(api, site, ids, f"{TOMORROW}T10:00"))
    second = ok(book(api, site, ids, f"{TOMORROW}T15:00"))
    ok(api.post("/downtimes", {"locationId": site, "reason": "closure", "start": f"{TOMORROW}T08:00",
                               "end": f"{TOMORROW}T13:00"}))  # fmt: skip

    ok(api.post(f"/bookings/{first['id']}/status", {"status": "cancelled"}))
    assert calls.bodies("/internal/charges") == []
    ok(api.post(f"/bookings/{second['id']}/status", {"status": "cancelled"}))
    assert [c["description"] for c in calls.bodies("/internal/charges")] == [
        "Late cancellation fee · Personal training"
    ]


def test_a_location_closed_refuses_bookings_sessions_and_seats(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token())
    site = tenant.site_a
    ids = setup_desk(api, site)
    spin = ok(api.post("/offerings", {"kind": "class", "name": "Spin", "minutes": 45, "price": 0, "capacity": 4}))
    ok(
        api.post(
            "/sessions",
            {"locationId": site, "offeringId": spin["id"], "staffId": ids["coach"], "start": f"{DAY_AFTER}T18:00"},
        )
    )
    session = ok(api.get("/booking-options", location=site))["sessions"][0]
    ok(
        api.post(
            "/downtimes", {"locationId": site, "reason": "closure", "note": "Flooded", "start": f"{TOMORROW}T00:00"}
        )
    )

    answer = slots(api, site, ids)
    assert answer["slots"] == []
    assert answer["reason"].startswith("Unavailable that day: Union Square · closure until further notice")
    assert book(api, site, ids, f"{DAY_AFTER}T10:00").status_code == 409
    again = api.post(
        "/sessions",
        {"locationId": site, "offeringId": spin["id"], "staffId": ids["coach"], "start": f"{TOMORROW}T19:00"},
    )
    assert again.status_code == 409
    seat = api.post(f"/bookings/{session['id']}/attendees", {"customerId": ids["member"]})
    assert seat.status_code == 409
    assert "Flooded" not in seat.json()["detail"]  # the note is for staff, the reason is what's shown
    # The other location carries on.
    other = setup_desk(api, tenant.site_b)
    assert slots(api, tenant.site_b, {**ids, **other})["slots"]


def test_an_offering_down_only_stops_that_offering(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token())
    site = tenant.site_a
    ids = setup_desk(api, site)
    massage = ok(api.post("/offerings", {"kind": "appointment", "name": "Massage", "minutes": 60, "price": 70}))
    ok(api.post("/downtimes", {"locationId": site, "offeringId": ids["pt"], "reason": "unfit",
                               "start": f"{TOMORROW}T06:00", "end": f"{DAY_AFTER}T06:00"}))  # fmt: skip
    assert slots(api, site, ids)["slots"] == []
    assert slots(api, site, {**ids, "pt": massage["id"]})["slots"]
    assert slots(api, site, ids, DAY_AFTER)["slots"]


def test_a_unit_under_repair_blocks_the_house_it_sits_in(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    rentals = {**FITNESS, "label": "Stays", "presets": [PRESETS["rental"]], "open": 480, "close": 1140}
    api = Api(tenant.token(template=rentals))
    site = tenant.site_a
    house = add(api, site, "asset", "Lake house", "House")
    add(api, site, "asset", "Lake house · room 1", "Room", parentId=house["id"])
    room2 = add(api, site, "asset", "Lake house · room 2", "Room", parentId=house["id"])
    whole = ok(api.post("/offerings", {"kind": "rental", "name": "Whole house", "price": 300, "unit": "night",
                                       "requires": [{"type": "asset", "role": "House"}]}))  # fmt: skip
    room = ok(api.post("/offerings", {"kind": "rental", "name": "One room", "price": 90, "unit": "night",
                                      "requires": [{"type": "asset", "role": "Room"}]}))  # fmt: skip
    ok(api.post("/downtimes", {"resourceId": room2["id"], "reason": "repair", "start": f"{TOMORROW}T00:00",
                               "end": f"{DAY_AFTER}T00:00"}))  # fmt: skip

    def free(offering: str) -> list[str]:
        return ok(api.get("/availability", location=site, offering=offering, day=TOMORROW))["slots"]

    assert free(whole["id"]) == []
    assert free(room["id"])  # room 1 is still let
    listed = {r["resource"]["name"]: r for r in ok(api.get("/resources"))["resources"]}
    assert listed["Lake house · room 2"]["downtime"] is None  # it starts tomorrow


def test_ending_and_withdrawing_downtime(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token())
    site = tenant.site_a
    ids = setup_desk(api, site)
    now = ok(api.post("/downtimes", {"resourceId": ids["coach"], "reason": "maintenance"}))
    planned = ok(
        api.post("/downtimes", {"resourceId": ids["coach"], "reason": "absence", "start": f"{DAY_AFTER}T06:00"})
    )
    assert ok(api.get("/resources"))["resources"][0]["downtime"] == "maintenance"
    assert next(a for a in ok(api.get("/today"))["alerts"] if a["id"] == "unavailable")["detail"].startswith("Omar")
    assert slots(api, site, ids)["slots"] == []

    assert ok(api.post(f"/downtimes/{now['id']}/end")) == {"withdrawn": False}
    assert ok(api.post(f"/downtimes/{planned['id']}/end")) == {"withdrawn": True}
    assert slots(api, site, ids)["slots"]
    assert [d["state"] for d in ok(api.get("/downtimes"))["downtimes"]] == ["over"]
    assert api.post(f"/downtimes/{now['id']}/end").status_code == 422

    bad = api.post("/downtimes", {"resourceId": ids["coach"], "reason": "repair", "start": f"{DAY_AFTER}T10:00",
                                  "end": f"{DAY_AFTER}T09:00"})  # fmt: skip
    assert bad.status_code == 422
    both = api.post("/downtimes", {"resourceId": ids["coach"], "offeringId": ids["pt"], "reason": "repair"})
    assert both.status_code == 422


def test_downtime_money_goes_to_the_ledger_or_to_the_customer(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    site = tenant.site_a
    ids = setup_desk(api, site)
    down = ok(api.post("/downtimes", {"locationId": site, "reason": "repair", "note": "Burst pipe"}))

    ok(api.post(f"/downtimes/{down['id']}/money", {"kind": "expense", "amount": "420.50", "category": "Plumber"}))
    ok(api.post(f"/downtimes/{down['id']}/money", {"kind": "income", "amount": 300, "description": "Insurance"}))
    ok(
        api.post(
            f"/downtimes/{down['id']}/money",
            {"kind": "income", "amount": 80, "description": "Broken mirror", "customerId": ids["member"]},
        )
    )
    expense, insurance, mirror = calls.bodies("/internal/entries")
    assert expense["kind"] == "expense"
    assert expense["amount"] == "420.50"
    assert expense["category"] == "Plumber"
    assert expense["refId"] == down["id"]
    assert expense["description"] == "Repair · Union Square"
    assert insurance["category"] == "repair"
    assert insurance["charged"] is False
    assert mirror["charged"] is True
    [charge] = calls.bodies("/internal/charges")
    assert charge["customerId"] == ids["member"]
    assert charge["source"] == "fee"
    assert charge["amount"] == "80.00"
    assert all(b["key"].startswith("ops-") for b in calls.bodies("/internal/entries"))

    refused = api.post(f"/downtimes/{down['id']}/money", {"kind": "expense", "amount": 5, "customerId": ids["member"]})
    assert refused.status_code == 422
    desk = Api(tenant.token(role="desk", perms=("bookings.manage",)))
    assert desk.post(f"/downtimes/{down['id']}/money", {"kind": "expense", "amount": 5}).status_code == 403
    assert desk.post("/downtimes", {"locationId": site, "reason": "maintenance"}).status_code == 200
    viewer = Api(tenant.token(role="viewer", perms=("analytics.view",)))
    assert viewer.post("/downtimes", {"locationId": site, "reason": "maintenance"}).status_code == 403
    assert ok(viewer.get("/downtimes"))["canEdit"] is False
