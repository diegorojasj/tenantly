"""Usage for Tenantly's bill (docs/BILLING.md §3) and what an unpaid Tenantly invoice holds back (§5.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .test_operations import TOMORROW, Api, ok, setup_desk

if TYPE_CHECKING:
    from .conftest import Calls, Tenant

pytestmark = pytest.mark.django_db(transaction=True)


def test_serving_a_customer_sends_usage_and_no_shows_or_refunds_dont(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    ids = setup_desk(api, tenant.site_a)
    body = {"locationId": tenant.site_a, "offeringId": ids["pt"], "customerId": ids["member"], "staffId": ids["coach"]}
    served = ok(api.post("/bookings", {**body, "start": f"{TOMORROW}T10:00"}))
    cancelled = ok(api.post("/bookings", {**body, "start": f"{TOMORROW}T12:00"}))
    assert calls.bodies("/internal/usage") == []  # booking someone isn't serving them yet

    ok(api.post(f"/bookings/{served['id']}/status", {"status": "checked_in"}))
    ok(api.post(f"/bookings/{served['id']}/status", {"status": "completed"}))
    ok(api.post(f"/bookings/{cancelled['id']}/status", {"status": "cancelled"}))

    events = calls.bodies("/internal/usage")
    assert [(e["metric"], e["source"], e["delta"]) for e in events] == [
        ("active_customers", "booking.checked_in", 1),
        ("active_customers", "booking.completed", 1),
        ("bookings", "booking.completed", 1),
    ]
    first, again, handled = events
    # Same customer, same booking: billing counts the source once, whatever the key.
    assert first["subjectKey"] == again["subjectKey"] == ids["member"]
    assert first["sourceRef"] == again["sourceRef"] == f"booking:{served['id']}"
    assert first["label"] == "Lena Okafor"
    assert handled["subjectKey"] == served["id"]
    # Each event is keyed by its outbox row, so a resend is recognised.
    assert len({e["key"] for e in events}) == 3


def test_class_seats_count_and_calling_the_class_off_reverses_them(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    spin = ok(api.post("/offerings", {"kind": "class", "name": "Spin", "minutes": 45, "price": 0, "capacity": 5}))
    coach = ok(api.post("/resources", {"locationId": tenant.site_a, "type": "staff", "name": "Omar", "role": "Ride"}))
    people = [ok(api.post("/customers", {"locationId": tenant.site_a, "name": n}))["id"] for n in ("Ann", "Ben")]
    session = {
        "locationId": tenant.site_a,
        "offeringId": spin["id"],
        "staffId": coach["id"],
        "start": f"{TOMORROW}T18:00",
    }
    ok(api.post("/sessions", session))
    sid = ok(api.get("/booking-options", location=tenant.site_a))["sessions"][0]["id"]
    for person in people:
        ok(api.post(f"/bookings/{sid}/attendees", {"customerId": person}))
    # A free class still counts: the business served them (the old meter missed $0 work).
    joined = calls.bodies("/internal/usage")
    assert [(e["subjectKey"], e["source"], e["delta"]) for e in joined] == [(p, "attendance", 1) for p in people]

    ok(api.post(f"/bookings/{sid}/status", {"status": "cancelled"}))
    reversed_ = calls.bodies("/internal/usage")[2:]
    assert [(e["subjectKey"], e["delta"]) for e in reversed_] == [(p, -1) for p in people]
    assert [e["sourceRef"] for e in reversed_] == [e["sourceRef"] for e in joined]


def test_selling_a_plan_counts_the_customer(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    ids = setup_desk(api, tenant.site_a)
    plan = ok(api.post("/offerings", {"kind": "plan", "name": "Monthly", "price": 99, "unit": "month"}))
    ok(api.post(f"/customers/{ids['member']}/plan", {"offeringId": plan["id"]}))
    [sold] = calls.bodies("/internal/usage")
    assert (sold["subjectKey"], sold["source"]) == (ids["member"], "plan.sold")


def test_an_unpaid_tenantly_invoice_holds_back_new_work_step_by_step(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    ids = setup_desk(Api(tenant.token()), tenant.site_a)
    body = {
        "locationId": tenant.site_a,
        "offeringId": ids["pt"],
        "customerId": ids["member"],
        "staffId": ids["coach"],
        "start": f"{TOMORROW}T10:00",
    }
    new_customer = {"locationId": tenant.site_a, "name": "Noor"}

    # Past due: reminders only, nothing stops.
    past_due = Api(tenant.token(billing={"status": "past_due"}))
    booking = ok(past_due.post("/bookings", body))
    ok(past_due.post("/customers", new_customer))

    # Limited: no new customers; existing ones still book.
    limited = Api(tenant.token(billing={"status": "limited"}))
    refused = limited.post("/customers", new_customer)
    assert refused.status_code == 403
    assert "overdue" in refused.json()["detail"]
    ok(limited.post("/bookings", {**body, "start": f"{TOMORROW}T12:00"}))

    # Restricted: no new bookings either, but the day's work carries on.
    restricted = Api(tenant.token(billing={"status": "restricted"}))
    assert restricted.post("/bookings", {**body, "start": f"{TOMORROW}T14:00"}).status_code == 403
    ok(restricted.post(f"/bookings/{booking['id']}/status", {"status": "checked_in"}))
    ok(restricted.post(f"/bookings/{booking['id']}/status", {"status": "completed"}))
    assert ok(restricted.get("/customers"))

    # Canceled: read-only.
    canceled = Api(tenant.token(billing={"status": "canceled"}))
    assert ok(canceled.get("/customers"))
    assert canceled.post(f"/bookings/{booking['id']}/status", {"status": "cancelled"}).status_code == 403
