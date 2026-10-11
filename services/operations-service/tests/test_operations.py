"""Operations end to end against a fresh, empty business."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.test import Client
from src.models import Booking, MoneyEvent

from .conftest import FITNESS, PRESETS

if TYPE_CHECKING:
    from .conftest import Calls, Tenant

# Transactional, so charges and refunds leave the outbox after commit as they do in production.
pytestmark = pytest.mark.django_db(transaction=True)

TOMORROW = (datetime.now(tz=UTC) + timedelta(days=1)).date().isoformat()


class Api:
    def __init__(self, token: str) -> None:
        self.client = Client()
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(path, params, **self.auth)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.client.post(path, body or {}, content_type="application/json", **self.auth)

    def put(self, path: str, body: dict[str, Any]) -> Any:
        return self.client.put(path, body, content_type="application/json", **self.auth)


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.content
    return response.json()


def setup_desk(api: Api, site: str) -> dict[str, str]:
    """The minimum a gym needs before its first booking."""
    pt = ok(api.post("/offerings", {"kind": "appointment", "name": "Personal training", "minutes": 60, "price": 90}))
    coach = ok(api.post("/resources", {"locationId": site, "type": "staff", "name": "Omar", "role": "Strength"}))
    member = ok(api.post("/customers", {"locationId": site, "name": "Lena Okafor", "fields": {"goal": "Strength"}}))
    return {"pt": pt["id"], "coach": coach["id"], "member": member["id"]}


def test_a_new_business_has_nothing_and_says_what_to_do(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token())
    today = ok(api.get("/today"))
    assert today["kpis"]["bookings"] == 0
    assert today["arrivals"] == []
    assert today["setup"]["done"] is False
    assert not any(today["setup"]["steps"].values())
    assert ok(api.get("/customers")) == []
    assert ok(api.get("/catalog"))["offerings"] == []


def test_book_free_times_only_and_never_double_book(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    ids = setup_desk(api, tenant.site_a)
    free = ok(api.get("/availability", location=tenant.site_a, offering=ids["pt"], staff=ids["coach"], day=TOMORROW))
    assert free["slots"][0] == "06:00"
    assert "10:00" in free["slots"]

    body = {
        "locationId": tenant.site_a,
        "offeringId": ids["pt"],
        "customerId": ids["member"],
        "staffId": ids["coach"],
        "start": f"{TOMORROW}T10:00",
    }
    created = ok(api.post("/bookings", body))
    assert created["status"] == "confirmed"
    clash = api.post("/bookings", {**body, "start": f"{TOMORROW}T10:30"})
    assert clash.status_code == 409
    assert "busy" in clash.json()["detail"]
    after = ok(api.get("/availability", location=tenant.site_a, offering=ids["pt"], staff=ids["coach"], day=TOMORROW))
    assert "10:00" not in after["slots"]
    assert "10:30" not in after["slots"]
    assert any(p.endswith("/internal/audit") for p in calls.paths())


def test_lifecycle_moves_forward_and_money_follows(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    ids = setup_desk(api, tenant.site_a)
    start = datetime.now(tz=UTC).replace(second=0, microsecond=0) + timedelta(days=1)
    start = start.replace(hour=12, minute=0)
    booking = ok(
        api.post(
            "/bookings",
            {
                "locationId": tenant.site_a,
                "offeringId": ids["pt"],
                "customerId": ids["member"],
                "staffId": ids["coach"],
                "start": start.strftime("%Y-%m-%dT%H:%M"),
            },
        )
    )
    skip = api.post(f"/bookings/{booking['id']}/status", {"status": "completed"})
    assert skip.status_code == 422
    assert ok(api.post(f"/bookings/{booking['id']}/status", {"status": "checked_in"}))["status"] == "checked_in"
    ok(api.post(f"/bookings/{booking['id']}/status", {"status": "completed"}))
    charge = calls.bodies("/internal/charges")[-1]
    assert charge["amount"] == "90.00"
    assert charge["source"] == "booking"


def test_the_tenants_template_drives_lifecycle_hours_words_and_defaults(tenant: Tenant, calls: Calls) -> None:
    """A template that differs from the built-in three is enforced from the token alone."""
    clinic = {
        **FITNESS,
        "label": "Clinic",
        "presets": [PRESETS["appointment"]],
        "resourceTypes": [{**FITNESS["resourceTypes"][0], "label": "Dentist"}],
        # No check-in step: a confirmed visit is completed directly, and can't be a no-show.
        "transitions": {"requested": ["confirmed"], "confirmed": ["completed", "cancelled"], "completed": []},
        "open": 9 * 60,
        "close": 17 * 60,
        "policyDefaults": {"booking.approval": True},
    }
    api = Api(tenant.token(template=clinic))
    ids = setup_desk(api, tenant.site_a)
    free = ok(api.get("/availability", location=tenant.site_a, offering=ids["pt"], staff=ids["coach"], day=TOMORROW))
    assert free["slots"][0] == "09:00"
    unstaffed = ok(api.get("/availability", location=tenant.site_a, offering=ids["pt"], day=TOMORROW))
    assert "Pick a dentist" in unstaffed["reason"]
    policies = {p["def"]["key"]: p for p in ok(api.get("/policies", scope=tenant.site_a))}
    assert policies["booking.approval"]["value"] is True
    assert policies["booking.approval"]["trail"][0]["label"] == "Default for Clinic"
    assert policies["docs.require.waiver"]["value"] == "Not needed"  # not in this template's defaults: the platform's

    body = {"locationId": tenant.site_a, "offeringId": ids["pt"], "customerId": ids["member"], "staffId": ids["coach"]}
    booking = ok(api.post("/bookings", {**body, "start": f"{TOMORROW}T10:00"}))
    assert booking["status"] == "requested"
    assert api.post("/bookings", {**body, "start": f"{TOMORROW}T08:00"}).status_code == 422  # before opening
    ok(api.post(f"/bookings/{booking['id']}/status", {"status": "confirmed"}))
    refused = api.post(f"/bookings/{booking['id']}/status", {"status": "checked_in"})
    assert refused.status_code == 422
    assert "booked booking can't become checked in" in refused.json()["detail"]
    assert ok(api.post(f"/bookings/{booking['id']}/status", {"status": "completed"}))["status"] == "completed"
    assert calls.bodies("/internal/charges")[-1]["source"] == "booking"


def test_classes_fill_up_drop_ins_pay_and_cancelling_refunds(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    spin = ok(api.post("/offerings", {"kind": "class", "name": "Spin", "minutes": 45, "price": 20, "capacity": 2}))
    coach = ok(
        api.post("/resources", {"locationId": tenant.site_a, "type": "staff", "name": "Omar", "role": "Cycling"})
    )
    people = [ok(api.post("/customers", {"locationId": tenant.site_a, "name": n}))["id"] for n in ("Ann", "Ben", "Cal")]
    created = ok(
        api.post(
            "/sessions",
            {
                "locationId": tenant.site_a,
                "offeringId": spin["id"],
                "staffId": coach["id"],
                "start": f"{TOMORROW}T18:00",
                "repeatWeeks": 2,
            },
        )
    )
    assert created["created"] == 2
    session = ok(api.get("/booking-options", location=tenant.site_a))["sessions"][0]
    ok(api.post(f"/bookings/{session['id']}/attendees", {"customerId": people[0]}))
    ok(api.post(f"/bookings/{session['id']}/attendees", {"customerId": people[1]}))
    full = api.post(f"/bookings/{session['id']}/attendees", {"customerId": people[2]})
    assert full.status_code == 409
    assert [c["source"] for c in calls.bodies("/internal/charges")] == ["dropin", "dropin"]
    ok(api.post(f"/bookings/{session['id']}/status", {"status": "cancelled"}))
    assert any(f"/internal/bookings/{session['id']}/refund" in p for p in calls.paths())


def test_scope_and_template_rules_are_enforced(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    desk = Api(
        tenant.token(
            role="location_manager",
            perms=("bookings.manage", "payments.collect", "config.write", "analytics.view"),
            home=tenant.site_a,
        )
    )
    refused = desk.post("/resources", {"locationId": tenant.site_b, "type": "staff", "name": "Eve", "role": "Yoga"})
    assert refused.status_code == 403
    ok(desk.post("/resources", {"locationId": tenant.site_a, "type": "staff", "name": "Omar", "role": "Yoga"}))
    no_pricing = desk.post("/offerings", {"kind": "appointment", "name": "PT", "minutes": 60, "price": 10})
    assert no_pricing.status_code == 403

    owner = Api(tenant.token())
    rental = owner.post(
        "/offerings",
        {
            "kind": "rental",
            "name": "Kayak",
            "minutes": 60,
            "price": 10,
            "requires": [{"type": "asset", "role": "Kayak"}],
        },
    )
    assert rental.status_code == 422
    assert "don't sell rentals" in rental.json()["detail"]
    assert {r["resource"]["locationId"] for r in ok(owner.get("/resources"))["resources"]} == {tenant.site_a}
    assert ok(desk.get("/resources", scope=tenant.site_b))["resources"][0]["resource"]["locationId"] == tenant.site_a


def test_policies_cascade_and_change_how_booking_behaves(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token())
    ids = setup_desk(api, tenant.site_a)
    waiver = next(p for p in ok(api.get("/policies", scope=tenant.site_a)) if p["def"]["key"] == "docs.require.waiver")
    assert waiver["value"] == "Remind"  # the fitness template starts by asking for waivers
    ok(api.put("/policies", {"scope": tenant.area, "key": "booking.approval", "value": True}))
    approval = next(p for p in ok(api.get("/policies", scope=tenant.site_a)) if p["def"]["key"] == "booking.approval")
    assert approval["value"] is True
    assert approval["trail"][approval["source"]]["label"] == "Manhattan"
    booking = ok(
        api.post(
            "/bookings",
            {
                "locationId": tenant.site_a,
                "offeringId": ids["pt"],
                "customerId": ids["member"],
                "staffId": ids["coach"],
                "start": f"{TOMORROW}T09:00",
            },
        )
    )
    assert booking["status"] == "requested"
    bad = api.put("/policies", {"scope": tenant.site_a, "key": "payments.noShowFee", "value": "Everything"})
    assert bad.status_code == 422


def test_money_waits_in_the_outbox_when_billing_is_down(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    ids = setup_desk(api, tenant.site_a)
    coach_b = ok(api.post("/resources", {"locationId": tenant.site_b, "type": "staff", "name": "Ivy", "role": "PT"}))
    start = (datetime.now(tz=UTC) + timedelta(days=1)).replace(hour=12, minute=0).strftime("%Y-%m-%dT%H:%M")
    # A Union Square member training in Brooklyn.
    body = {
        "locationId": tenant.site_b,
        "offeringId": ids["pt"],
        "customerId": ids["member"],
        "staffId": coach_b["id"],
        "start": start,
    }
    booking = ok(api.post("/bookings", body))
    ok(api.post(f"/bookings/{booking['id']}/status", {"status": "checked_in"}))

    calls.down.add("billing.test")
    done = ok(api.post(f"/bookings/{booking['id']}/status", {"status": "completed"}))
    assert done["status"] == "completed"  # the desk isn't blocked by billing
    assert calls.bodies("/internal/charges") == []
    pending = MoneyEvent.objects.get(sent_at__isnull=True)
    assert pending.attempts == 1
    assert "unavailable" in pending.error or "Request failed" in pending.error

    calls.down.clear()
    call_command("send_money")
    call_command("send_money")  # nothing left: sent exactly once
    [charge] = calls.bodies("/internal/charges")
    assert charge["key"] == f"ops-{pending.id}"
    assert charge["locationId"] == tenant.site_b  # filed where the work happened


def test_a_desk_only_books_customers_in_its_scope(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    owner = Api(tenant.token())
    ids = setup_desk(owner, tenant.site_a)
    coach_b = ok(owner.post("/resources", {"locationId": tenant.site_b, "type": "staff", "name": "Ivy", "role": "PT"}))
    desk_b = Api(
        tenant.token(
            role="location_manager",
            perms=("bookings.manage", "payments.collect", "config.write", "analytics.view"),
            home=tenant.site_b,
        )
    )
    refused = desk_b.post(
        "/bookings",
        {
            "locationId": tenant.site_b,
            "offeringId": ids["pt"],
            "customerId": ids["member"],
            "staffId": coach_b["id"],
            "start": f"{TOMORROW}T10:00",
        },
    )
    assert refused.status_code == 422


def test_bounds_on_policies_and_the_shared_catalog(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    owner = Api(tenant.token())
    huge = owner.put("/policies", {"scope": tenant.site_a, "key": "booking.window", "value": 10**12})
    assert huge.status_code == 422
    area = Api(tenant.token(role="regional_manager", perms=("pricing.write", "config.write"), home=tenant.area))
    shared = area.post("/offerings", {"kind": "appointment", "name": "PT", "minutes": 60, "price": 10})
    assert shared.status_code == 403


def test_hours_and_times_follow_the_locations_own_zone(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    """Union Square runs on New York time with its own hours; Brooklyn keeps UTC and the template's."""
    api = Api(tenant.token(site_a_clock=("America/New_York", (9 * 60, 17 * 60))))
    ids = setup_desk(api, tenant.site_a)
    day = (datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(days=2)).date().isoformat()
    free = ok(api.get("/availability", location=tenant.site_a, offering=ids["pt"], staff=ids["coach"], day=day))
    assert free["slots"][0] == "09:00"
    assert free["slots"][-1] == "16:00"

    body = {"locationId": tenant.site_a, "offeringId": ids["pt"], "customerId": ids["member"], "staffId": ids["coach"]}
    # 07:00 in New York is 11:00 or 12:00 UTC: inside the template's hours, outside this location's.
    early = api.post("/bookings", {**body, "start": f"{day}T07:00"})
    assert early.status_code == 422
    assert "09:00 to 17:00" in early.json()["detail"]
    created = ok(api.post("/bookings", {**body, "start": f"{day}T09:00"}))
    stored = Booking.objects.get(id=created["id"])
    expected = datetime.fromisoformat(f"{day}T09:00").replace(tzinfo=ZoneInfo("America/New_York"))
    assert stored.start == expected  # aware, compared as instants
    assert stored.start.astimezone(UTC).hour in {13, 14}  # EDT or EST
    listed = ok(api.get("/calendar", scope=tenant.site_a, day=day))
    assert (listed["open"], listed["close"], listed["tz"]) == (540, 1020, "America/New_York")
    shown = listed["board"]["bookings"][0]
    assert (shown["start"], shown["end"], shown["tz"]) == (f"{day}T09:00", f"{day}T10:00", "America/New_York")

    ike = {"locationId": tenant.site_b, "type": "staff", "name": "Ike", "role": "Yoga"}
    elsewhere = ok(api.post("/resources", ike))
    utc = ok(api.get("/availability", location=tenant.site_b, offering=ids["pt"], staff=elsewhere["id"], day=day))
    assert utc["slots"][0] == "06:00"


RENTALS: dict[str, Any] = {
    **FITNESS,
    "label": "Rentals",
    "presets": [PRESETS["rental"], PRESETS["class"]],
    "open": 480,
    "close": 1140,
}


def test_nightly_rentals_span_days_and_are_priced_per_night(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token(template=RENTALS))
    cabin = {
        "kind": "rental",
        "name": "Lake cabin",
        "price": 120,
        "requires": [{"type": "asset", "role": "Cabin"}],
        "unit": "night",
    }
    nightly = ok(api.post("/offerings", cabin))
    assert (nightly["unit"], nightly["time"], nightly["capacity"]) == ("night", "span", 1)
    hourly = ok(api.post("/offerings", {**cabin, "name": "Day use", "price": 20, "unit": None}))
    assert (hourly["unit"], hourly["time"]) == ("hour", "window")
    unnamed = api.post("/offerings", {**cabin, "requires": None})
    assert unnamed.status_code == 422
    assert "Say which kind of room" in unnamed.json()["detail"]
    ok(api.post("/resources", {"locationId": tenant.site_a, "type": "asset", "name": "Cabin 1", "role": "Cabin"}))
    renter = ok(api.post("/customers", {"locationId": tenant.site_a, "name": "Sam Reyes"}))

    free = ok(api.get("/availability", location=tenant.site_a, offering=nightly["id"], day=TOMORROW, units=3))
    assert "15:00" in free["slots"]
    body = {"locationId": tenant.site_a, "customerId": renter["id"], "start": f"{TOMORROW}T15:00"}
    stay = ok(api.post("/bookings", {**body, "offeringId": nightly["id"], "units": 3}))
    booking = Booking.objects.get(id=stay["id"])
    assert booking.price == Decimal("360.00")  # three nights at 120
    assert booking.end - booking.start == timedelta(days=3)

    # The only cabin is taken for the whole stay, not just the first day.
    later = (datetime.fromisoformat(TOMORROW) + timedelta(days=2)).date().isoformat()
    clash = api.post("/bookings", {**body, "offeringId": nightly["id"], "start": f"{later}T10:00", "units": 1})
    assert clash.status_code == 409
    busy = ok(api.get("/availability", location=tenant.site_a, offering=nightly["id"], day=later, units=1))
    assert busy["slots"] == []
    middle = ok(api.get("/calendar", scope=tenant.site_a, day=later))  # the stay shows on each day it covers
    assert [b["id"] for b in middle["board"]["bookings"]] == [stay["id"]]

    # Hourly rentals keep the one-day, eight-hour window.
    after = (datetime.fromisoformat(TOMORROW) + timedelta(days=5)).date().isoformat()
    day_use = ok(api.post("/bookings", {**body, "offeringId": hourly["id"], "start": f"{after}T09:00", "minutes": 600}))
    hours = Booking.objects.get(id=day_use["id"])
    assert hours.end - hours.start == timedelta(hours=8)
    assert hours.price == Decimal("160.00")


def test_errors_and_policy_words_follow_the_requests_language(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token())
    spanish = {**api.auth, "HTTP_ACCEPT_LANGUAGE": "es"}
    bad = api.client.put(
        "/policies",
        {"scope": tenant.site_a, "key": "payments.noShowFee", "value": "Everything"},
        content_type="application/json",
        **spanish,
    )
    assert bad.status_code == 422
    assert bad.json()["detail"] == "Ese no es un valor válido para “Tarifa por inasistencia”"
    rows = api.client.get("/policies", {"scope": tenant.site_a}, **spanish).json()
    fee = next(p for p in rows if p["def"]["key"] == "payments.noShowFee")
    assert fee["def"]["group"] == "Pagos"
    assert fee["def"]["options"] == ["None", "25% of price", "50% of price", "Full price"]  # stored values
    assert fee["def"]["optionLabels"]["Full price"] == "Precio completo"
    # English stays the default.
    assert api.put("/policies", {"scope": tenant.site_a, "key": "x", "value": 1}).json()["detail"] == "Unknown policy"
