"""Fulfilment rules, requirement lists, typed attributes and nesting (docs/PLATFORM.md gaps 3-4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from src.models import Booking, Offering

from .conftest import FITNESS, PRESETS
from .test_operations import TOMORROW, Api, ok

if TYPE_CHECKING:
    from .conftest import Calls, Tenant

pytestmark = pytest.mark.django_db(transaction=True)

# A template none of the original three could express: a check-up takes a dentist the desk
# picks, plus a free hygienist and a free chair with an X-ray, assigned automatically.
CLINIC: dict[str, Any] = {
    **FITNESS,
    "label": "Clinic",
    "open": 9 * 60,
    "close": 17 * 60,
    "resourceTypes": [
        {"key": "staff", "label": "Clinician", "plural": "Clinicians", "people": True, "roleLabel": "Role"},
        {
            "key": "chair",
            "label": "Chair",
            "plural": "Chairs",
            "people": False,
            "roleLabel": "Type",
            "attributes": [
                {"key": "xray", "label": "X-ray", "type": "bool"},
                {"key": "floor", "label": "Floor", "type": "number", "required": True},
                {"key": "side", "label": "Side", "type": "choice", "options": ["North", "South"]},
            ],
        },
    ],
    "presets": [
        {
            "key": "checkup",
            "label": "Check-up",
            "plural": "Check-ups",
            "capacity": 1,
            "time": "slot",
            "units": ["session"],
            "place": "on_site",
            "requires": [
                {"type": "staff", "quantity": 1, "pick": True, "role": "Dentist"},
                {"type": "staff", "quantity": 1, "pick": False, "role": "Hygienist"},
                {"type": "chair", "quantity": 1, "where": {"xray": True}},
            ],
        },
        PRESETS["appointment"],
        PRESETS["plan"],
    ],
}


def add(api: Api, site: str, type_: str, name: str, role: str, **extra: Any) -> dict[str, Any]:
    return ok(api.post("/resources", {"locationId": site, "type": type_, "name": name, "role": role, **extra}))


def test_requirement_lists_with_quantities_and_typed_attributes(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token(template=CLINIC))
    site = tenant.site_a
    unknown = api.post("/resources", {"locationId": site, "type": "asset", "name": "Room 1", "role": "Room"})
    assert unknown.status_code == 422  # this template has no "asset" type
    bad = {"locationId": site, "type": "chair", "name": "Chair 1", "role": "Dental"}
    assert "Enter floor" in api.post("/resources", bad).json()["detail"]
    assert "must be a number" in api.post("/resources", {**bad, "attributes": {"floor": "two"}}).json()["detail"]
    assert "one of: North" in api.post("/resources", {**bad, "attributes": {"floor": 1, "side": "Up"}}).json()["detail"]
    assert "Unknown field" in api.post("/resources", {**bad, "attributes": {"floor": 1, "wifi": 1}}).json()["detail"]

    plain = add(api, site, "chair", "Chair 1", "Dental", attributes={"floor": "1", "xray": False})
    assert plain["attributes"] == {"floor": 1, "xray": False}
    xray = add(api, site, "chair", "Chair 2", "Dental", attributes={"floor": 2, "xray": True, "side": "North"})
    dentists = [add(api, site, "staff", n, "Dentist")["id"] for n in ("Dr Ruiz", "Dr Chen")]
    hygienist = add(api, site, "staff", "Hana", "Hygienist")
    patient = ok(api.post("/customers", {"locationId": site, "name": "Pat"}))["id"]

    checkup = ok(api.post("/offerings", {"kind": "checkup", "name": "Check-up", "minutes": 30, "price": 80}))
    assert [(r["role"], r["quantity"], r["pick"]) for r in checkup["requires"]] == [
        ("Dentist", 1, True),
        ("Hygienist", 1, False),
        (None, 1, False),
    ]
    assert checkup["requires"][2]["where"] == {"xray": True}

    unpicked = ok(api.get("/availability", location=site, offering=checkup["id"], day=TOMORROW))
    assert "Pick a dentist" in unpicked["reason"]
    hygienist_only = api.get(
        "/availability", location=site, offering=checkup["id"], staff=hygienist["id"], day=TOMORROW
    )
    assert "Pick a dentist" in ok(hygienist_only)["reason"]  # the pick must match the requirement's role
    free = ok(api.get("/availability", location=site, offering=checkup["id"], staff=dentists[0], day=TOMORROW))
    assert free["slots"][0] == "09:00"

    body = {"locationId": site, "offeringId": checkup["id"], "customerId": patient, "start": f"{TOMORROW}T10:00"}
    first = ok(api.post("/bookings", {**body, "resourceIds": [dentists[0]]}))
    held = set(Booking.objects.get(id=first["id"]).resources.values_list("name", flat=True))
    assert held == {"Dr Ruiz", "Hana", "Chair 2"}  # only the chair with an X-ray qualifies

    # Another dentist is free, but the only hygienist and the only X-ray chair are not.
    clash = api.post("/bookings", {**body, "staffId": dentists[1]})
    assert clash.status_code == 409
    assert "No hygienist free" in clash.json()["detail"]
    other = ok(api.get("/availability", location=site, offering=checkup["id"], staff=dentists[1], day=TOMORROW))
    assert "10:00" not in other["slots"]
    assert "11:00" in other["slots"]
    assert xray["id"] in ok(api.get("/calendar", scope=site, day=TOMORROW))["board"]["bookings"][0]["resourceIds"]

    # Quantities: two hygienists on a long procedure, only one on staff.
    reqs = [
        {"type": "staff", "role": "Dentist"},
        {"type": "staff", "role": "Hygienist", "quantity": 2, "pick": False},
    ]
    surgery = ok(
        api.post("/offerings", {"kind": "checkup", "name": "Surgery", "minutes": 60, "price": 400, "requires": reqs})
    )
    short = ok(api.get("/availability", location=site, offering=surgery["id"], staff=dentists[1], day=TOMORROW))
    assert "No hygienist is in service here" in short["reason"]
    add(api, site, "staff", "Hugo", "Hygienist")
    enough = ok(api.get("/availability", location=site, offering=surgery["id"], staff=dentists[1], day=TOMORROW))
    assert "09:00" in enough["slots"]
    assert "10:00" not in enough["slots"]  # Hana is with the check-up then


def test_rules_not_kinds_decide_how_an_offering_books(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token())
    coach = add(api, tenant.site_a, "staff", "Omar", "Strength")
    # An appointment preset with three seats is a small-group session, booked like a class.
    trio = ok(
        api.post("/offerings", {"kind": "appointment", "name": "Trio PT", "minutes": 60, "price": 40, "capacity": 3})
    )
    assert (trio["kind"], trio["capacity"], trio["time"]) == ("appointment", 3, "slot")
    # At the customer's home, with no room: place is a rule too.
    home = ok(api.post("/offerings", {"kind": "appointment", "name": "Home PT", "price": 120, "place": "at_customer"}))
    assert home["place"] == "at_customer"
    pack = ok(
        api.post("/offerings", {"kind": "plan", "name": "10 classes", "price": 150, "unit": "pack", "credits": 10})
    )
    assert (pack["time"], pack["capacity"], pack["requires"]) == ("none", None, [])
    wrong = api.post("/offerings", {"kind": "appointment", "name": "PT", "price": 1, "unit": "night"})
    assert wrong.status_code == 422

    options = ok(api.get("/booking-options", location=tenant.site_a))
    assert [o["name"] for o in options["offerings"]] == ["Home PT"]
    assert [o["name"] for o in options["classes"]] == ["Trio PT"]
    assert [r["name"] for r in options["resources"]] == ["Omar"]
    created = ok(
        api.post(
            "/sessions",
            {
                "locationId": tenant.site_a,
                "offeringId": trio["id"],
                "staffId": coach["id"],
                "start": f"{TOMORROW}T08:00",
            },
        )
    )
    assert created["created"] == 1


def test_nested_resources_block_each_other(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    rentals = {**FITNESS, "label": "Stays", "presets": [PRESETS["rental"]], "open": 480, "close": 1140}
    api = Api(tenant.token(template=rentals))
    site = tenant.site_a
    house = add(api, site, "asset", "Lake house", "House")
    room = add(api, site, "asset", "Lake house · room 1", "Room", parentId=house["id"])
    assert room["parentId"] == house["id"]
    elsewhere = api.post(
        "/resources",
        {"locationId": tenant.site_b, "type": "asset", "name": "Annex", "role": "Room", "parentId": house["id"]},
    )
    assert elsewhere.status_code == 422

    whole = ok(
        api.post(
            "/offerings",
            {
                "kind": "rental",
                "name": "Whole house",
                "price": 300,
                "unit": "night",
                "requires": [{"type": "asset", "role": "House"}],
            },
        )
    )
    single = ok(
        api.post(
            "/offerings",
            {
                "kind": "rental",
                "name": "One room",
                "price": 90,
                "unit": "night",
                "requires": [{"type": "asset", "role": "Room"}],
            },
        )
    )
    guest = ok(api.post("/customers", {"locationId": site, "name": "Sam"}))["id"]
    body = {"locationId": site, "customerId": guest, "units": 2}
    ok(api.post("/bookings", {**body, "offeringId": single["id"], "start": f"{TOMORROW}T15:00"}))
    # The room is let, so the house can't be let whole over those nights…
    blocked = api.post("/bookings", {**body, "offeringId": whole["id"], "start": f"{TOMORROW}T16:00"})
    assert blocked.status_code == 409
    later = (datetime.now(tz=UTC) + timedelta(days=5)).date().isoformat()
    ok(api.post("/bookings", {**body, "offeringId": whole["id"], "start": f"{later}T15:00"}))
    # …and while the house is let whole, its room isn't free either.
    assert ok(api.get("/availability", location=site, offering=single["id"], day=later, units=1))["slots"] == []


def test_migration_turns_kinds_into_rules(transactional_db: None) -> None:  # noqa: ARG001
    """0003 rewrites every offering's kind, needs_staff and asset_type as rules that book the same way."""
    executor = MigrationExecutor(connection)
    before, after = [("operations", "0002_money_outbox")], [("operations", "0003_fulfilment_rules_resource_types")]
    executor.migrate(before)
    old = executor.loader.project_state(before).apps.get_model("operations", "Offering")
    tid = uuid.uuid4()
    rows = {
        "pt": {"kind": "appointment", "unit": "session", "minutes": 60, "needs_staff": True},
        "spin": {
            "kind": "class",
            "unit": "session",
            "minutes": 45,
            "capacity": 12,
            "needs_staff": True,
            "asset_type": "Room",
        },
        "kayak": {"kind": "rental", "unit": "hour", "minutes": 60, "asset_type": "Kayak"},
        "cabin": {"kind": "rental", "unit": "night", "minutes": 60, "asset_type": "Cabin"},
        "fix": {"kind": "visit", "unit": "session", "minutes": 90, "needs_staff": True, "asset_type": "Van"},
        "care": {"kind": "plan", "unit": "month"},
    }
    for name, fields in rows.items():
        old.objects.create(tenant_id=tid, name=name, price=10, **fields)
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(after)
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes("operations"))

    got = {o.name: o for o in Offering.objects.filter(tenant_id=tid)}
    staff = {"type": "staff", "quantity": 1, "pick": True, "role": None}

    def asset(role: str) -> dict[str, Any]:
        return {"type": "asset", "quantity": 1, "pick": False, "role": role}

    assert (got["pt"].time, got["pt"].capacity, got["pt"].requires) == ("slot", 1, [staff])
    assert (got["spin"].capacity, got["spin"].requires) == (12, [staff, asset("Room")])
    assert (got["kayak"].time, got["kayak"].requires) == ("window", [asset("Kayak")])
    assert got["cabin"].time == "span"
    assert (got["fix"].place, got["fix"].requires) == ("at_customer", [staff, asset("Van")])
    assert (got["care"].time, got["care"].capacity, got["care"].requires) == ("none", None, [])
