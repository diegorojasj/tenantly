"""Parties, typed custom fields and documents with expiry (docs/PLATFORM.md gaps 5-6)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from src.models import Attendance, Booking, Document, PolicyOverride, Subscription

from .conftest import FITNESS, PRESETS
from .test_operations import TOMORROW, Api, ok, setup_desk

if TYPE_CHECKING:
    from .conftest import Calls, Tenant

pytestmark = pytest.mark.django_db(transaction=True)

STAFF = {"type": "staff", "quantity": 1, "pick": True}

# A pet groomer: a groom is for one pet, which needs a rabies vaccination on file; every
# customer signs a waiver; a booking records the pet's coat length.
GROOMER: dict[str, Any] = {
    **FITNESS,
    "label": "Grooming",
    "presets": [
        {
            "key": "groom",
            "label": "Groom",
            "plural": "Grooms",
            "capacity": 1,
            "time": "slot",
            "units": ["session"],
            "place": "on_site",
            "requires": [STAFF],
            "subject": "pet",
        },
        PRESETS["class"],
        PRESETS["plan"],
    ],
    "fields": {
        "customer": [
            {"key": "source", "label": "Heard of us", "type": "choice", "options": ["Friend", "Web"]},
            {"key": "phone2", "label": "Second phone", "type": "text", "pii": True},
            {"key": "licence", "label": "Licence valid until", "type": "date", "expires": True},
        ],
        "account": [{"key": "vat", "label": "VAT number", "type": "text"}],
        "booking": [{"key": "coat", "label": "Coat", "type": "choice", "options": ["Short", "Long"], "required": True}],
        "offering": [{"key": "sedation", "label": "Sedation", "type": "bool"}],
    },
    "accountTypes": [
        {"key": "household", "label": "Household", "plural": "Households", "fields": []},
        {"key": "business", "label": "Kennel", "plural": "Kennels", "fields": []},
    ],
    "subjectTypes": [
        {
            "key": "pet",
            "label": "Pet",
            "plural": "Pets",
            "fields": [
                {"key": "species", "label": "Species", "type": "choice", "options": ["Dog", "Cat"], "required": True},
                {"key": "weight", "label": "Weight", "type": "number"},
            ],
        },
        {"key": "vehicle", "label": "Vehicle", "plural": "Vehicles", "fields": []},
    ],
    "documents": [
        {"key": "waiver", "label": "Waiver", "appliesTo": "customer", "validDays": None},
        {
            "key": "rabies",
            "label": "Rabies vaccination",
            "appliesTo": "subject",
            "subjectType": "pet",
            "validDays": 365,
        },
    ],
    "policyDefaults": {"docs.require.waiver": "Remind", "docs.require.rabies": "Required to book"},
}


def _today() -> date:
    return datetime.now(tz=UTC).date()


def test_typed_fields_are_validated_masked_and_expire(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token(template=GROOMER))
    site = tenant.site_a
    body = {"locationId": site, "name": "Rosa"}
    assert "Unknown field" in api.post("/customers", {**body, "fields": {"shoe": "9"}}).json()["detail"]
    assert "one of: Friend" in api.post("/customers", {**body, "fields": {"source": "TV"}}).json()["detail"]
    assert "must be a date" in api.post("/customers", {**body, "fields": {"licence": "soon"}}).json()["detail"]
    lapsed = (_today() - timedelta(days=1)).isoformat()
    fields = {"source": "Web", "phone2": "555-0100", "licence": lapsed}
    rosa = ok(api.post("/customers", {**body, "fields": fields}))["id"]

    row = next(c for c in ok(api.get("/customers")) if c["id"] == rosa)
    assert row["fields"] == fields
    assert row["expiredFields"] == ["licence"]
    # Someone who only reads the numbers doesn't see personal data.
    analyst = Api(tenant.token(template=GROOMER, perms=("analytics.view",)))
    seen = next(c for c in ok(analyst.get("/customers")) if c["id"] == rosa)
    assert "phone2" not in seen["fields"]
    assert seen["fields"]["source"] == "Web"

    offering = {"kind": "groom", "name": "Full groom", "minutes": 60, "price": 50}
    assert api.post("/offerings", {**offering, "fields": {"sedation": "maybe"}}).status_code == 422
    groom = ok(api.post("/offerings", {**offering, "fields": {"sedation": False}}))
    assert (groom["subjectType"], groom["fields"]) == ("pet", {"sedation": False})


def _household(api: Api, site: str) -> dict[str, Any]:
    """A groomer, a groom, and the Ruiz household (Ana, her son Leo) with their dog Rex and Ana's van."""
    groomer = ok(api.post("/resources", {"locationId": site, "type": "staff", "name": "Ivo", "role": "Groomer"}))
    groom = ok(api.post("/offerings", {"kind": "groom", "name": "Full groom", "minutes": 60, "price": 50}))

    # A household opened with its first member; a second member joins it.
    ana = ok(
        api.post(
            "/customers",
            {"locationId": site, "name": "Ana", "accountType": "household", "accountName": "The Ruiz family"},
        )
    )["id"]
    household = ok(api.get("/accounts"))[0]
    assert (household["name"], household["typeLabel"]) == ("The Ruiz family", "Household")
    leo = ok(
        api.post("/customers", {"locationId": site, "name": "Leo", "accountId": household["id"], "accountRole": "Son"})
    )["id"]
    assert {c["name"] for c in ok(api.get("/accounts"))[0]["contacts"]} == {"Ana", "Leo"}
    assert api.post("/accounts", {"locationId": site, "type": "club", "name": "X Club"}).status_code == 422

    # The family's dog belongs to the household, so either member can bring it in.
    assert (
        "Enter species"
        in api.post("/subjects", {"type": "pet", "name": "Rex", "accountId": household["id"]}).json()["detail"]
    )
    rex = ok(
        api.post(
            "/subjects", {"type": "pet", "name": "Rex", "accountId": household["id"], "fields": {"species": "Dog"}}
        )
    )
    van = ok(api.post("/subjects", {"type": "vehicle", "name": "Van", "customerId": ana}))
    assert api.post("/subjects", {"type": "pet", "name": "Tom", "fields": {"species": "Cat"}}).status_code == 422

    return {"groomer": groomer, "groom": groom, "ana": ana, "leo": leo, "rex": rex, "van": van}


def test_accounts_group_customers_and_own_subjects(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token(template=GROOMER))
    site = tenant.site_a
    h = _household(api, site)
    leo, rex, van = h["leo"], h["rex"], h["van"]
    options = ok(api.get("/booking-options", location=site))
    leo_row = next(c for c in options["customers"] if c["id"] == leo)
    assert [s["name"] for s in leo_row["subjects"]] == ["Rex"]
    assert options["bookingFields"][0]["key"] == "coat"

    body = {"locationId": site, "offeringId": h["groom"]["id"], "customerId": leo, "staffId": h["groomer"]["id"]}
    at = {**body, "start": f"{TOMORROW}T10:00", "fields": {"coat": "Long"}}
    assert "Pick which of Leo's pets" in api.post("/bookings", at).json()["detail"]
    assert "Pick which of Leo's pets" in api.post("/bookings", {**at, "subjectId": van["id"]}).json()["detail"]
    assert "Enter coat" in api.post("/bookings", {**at, "subjectId": rex["id"], "fields": {}}).json()["detail"]
    profile = ok(api.get(f"/customers/{leo}"))
    assert profile["customer"]["account"]["role"] == "Son"
    assert [c["name"] for c in profile["contacts"]] == ["Ana"]
    assert [s["name"] for s in profile["subjects"]] == ["Rex"]


def test_documents_with_expiry_gate_the_booking_when_the_policy_requires(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    api = Api(tenant.token(template=GROOMER))
    site = tenant.site_a
    h = _household(api, site)
    ana, leo, rex, van = h["ana"], h["leo"], h["rex"], h["van"]
    body = {"locationId": site, "offeringId": h["groom"]["id"], "customerId": leo, "staffId": h["groomer"]["id"]}
    at = {**body, "start": f"{TOMORROW}T10:00", "fields": {"coat": "Long"}}
    # The policy requires a current rabies vaccination for the pet before booking.
    refused = api.post("/bookings", {**at, "subjectId": rex["id"]})
    assert refused.status_code == 422
    assert "needs a valid rabies vaccination" in refused.json()["detail"]

    # An old certificate (issued 400 days ago, valid 365) is on file but expired.
    old = (_today() - timedelta(days=400)).isoformat()
    ok(api.post(f"/customers/{leo}/documents", {"type": "rabies", "subjectId": rex["id"], "issued": old}))
    assert api.post("/bookings", {**at, "subjectId": rex["id"]}).status_code == 422
    assert (
        "for a pet"
        in api.post(f"/customers/{ana}/documents", {"type": "rabies", "subjectId": van["id"]}).json()["detail"]
    )
    ok(api.post(f"/customers/{leo}/documents", {"type": "rabies", "subjectId": rex["id"], "reference": "VET-1"}))
    booked = ok(api.post("/bookings", {**at, "subjectId": rex["id"]}))
    stored = Booking.objects.get(id=booked["id"])
    assert (stored.subject_id, stored.fields) == (uuid.UUID(rex["id"]), {"coat": "Long"})
    listed = ok(api.get("/bookings", range="upcoming"))["bookings"][0]
    assert (listed["subjectName"], listed["fields"]) == ("Rex", {"coat": "Long"})

    # The waiver only reminds: listed as missing, never blocking.
    profile = ok(api.get(f"/customers/{leo}"))
    assert profile["customer"]["missingDocuments"] == [{"key": "waiver", "label": "Waiver"}]
    assert profile["subjectMissing"] == {rex["id"]: []}
    levels = {d["key"]: d["level"] for d in profile["documentTypes"]}
    assert levels == {"waiver": "Remind", "rabies": "Required to book"}
    rabies = [d for d in profile["customer"]["documents"] if d["type"] == "rabies"]
    assert [d["valid"] for d in rabies] == [True, False]
    assert rabies[0]["expires"] == (_today() + timedelta(days=365)).isoformat()

    # Raise the waiver to "required to book" at one location only.
    ok(api.put("/policies", {"scope": site, "key": "docs.require.waiver", "value": "Required to book"}))
    later = {**at, "subjectId": rex["id"], "start": f"{TOMORROW}T12:00"}
    assert "needs a valid waiver" in api.post("/bookings", later).json()["detail"]
    ok(api.post(f"/customers/{leo}/documents", {"type": "waiver"}))
    ok(api.post("/bookings", later))
    assert ok(api.get(f"/customers/{leo}"))["customer"]["missingDocuments"] == []
    future = (_today() + timedelta(days=3)).isoformat()
    assert api.post(f"/customers/{leo}/documents", {"type": "waiver", "issued": future}).status_code == 422


def test_several_subscriptions_cover_classes_in_order(tenant: Tenant, calls: Calls) -> None:
    api = Api(tenant.token())
    site = tenant.site_a
    ids = setup_desk(api, site)
    member = ids["member"]
    monthly = ok(api.post("/offerings", {"kind": "plan", "name": "Unlimited", "price": 99, "unit": "month"}))
    pack = ok(api.post("/offerings", {"kind": "plan", "name": "5 classes", "price": 60, "unit": "pack", "credits": 5}))
    spin = ok(api.post("/offerings", {"kind": "class", "name": "Spin", "minutes": 45, "price": 20, "capacity": 8}))
    ok(api.post("/sessions", {"locationId": site, "offeringId": spin["id"], "staffId": ids["coach"],
                              "start": f"{TOMORROW}T18:00", "repeatWeeks": 3}))  # fmt: skip
    sessions = [{"id": str(b.id)} for b in Booking.objects.filter(offering_id=spin["id"]).order_by("start")]

    ok(api.post(f"/customers/{member}/plan", {"offeringId": monthly["id"]}))
    ok(api.post(f"/customers/{member}/plan", {"offeringId": pack["id"]}))
    subs = ok(api.get(f"/customers/{member}"))["customer"]["subscriptions"]
    assert [(s["name"], s["credits"]) for s in subs] == [("Unlimited", None), ("5 classes", 5)]
    catalog = {i["offering"]["name"]: i for i in ok(api.get("/catalog"))["offerings"]}
    assert catalog["Unlimited"]["subscribers"] == catalog["5 classes"]["subscribers"] == 1

    # The monthly plan covers the first class: no charge, no credit spent.
    ok(api.post(f"/bookings/{sessions[0]['id']}/attendees", {"customerId": member}))
    assert [c["source"] for c in calls.bodies("/internal/charges")] == ["plan", "plan"]
    assert Subscription.objects.get(id=subs[1]["id"]).credits == 5

    # Without it, the pack pays; calling the class off gives that credit back to the pack.
    ok(api.post(f"/customers/{member}/subscriptions/{subs[0]['id']}/cancel"))
    ok(api.post(f"/bookings/{sessions[1]['id']}/attendees", {"customerId": member}))
    assert Subscription.objects.get(id=subs[1]["id"]).credits == 4
    assert Attendance.objects.get(booking_id=sessions[1]["id"]).subscription_id == uuid.UUID(subs[1]["id"])
    ok(api.post(f"/bookings/{sessions[1]['id']}/status", {"status": "cancelled"}))
    assert Subscription.objects.get(id=subs[1]["id"]).credits == 5

    # Selling a pack they already hold tops it up instead of opening another.
    ok(api.post(f"/customers/{member}/plan", {"offeringId": pack["id"]}))
    subs = ok(api.get(f"/customers/{member}"))["customer"]["subscriptions"]
    assert [(s["name"], s["credits"]) for s in subs] == [("5 classes", 10)]
    Subscription.objects.filter(id=subs[0]["id"]).update(credits=0)
    empty = api.post(f"/bookings/{sessions[2]['id']}/attendees", {"customerId": member})
    assert "no credits left" in empty.json()["detail"]
    assert api.post(f"/customers/{member}/subscriptions/{subs[0]['id']}/cancel").status_code == 200
    assert api.post(f"/customers/{member}/subscriptions/{subs[0]['id']}/cancel").status_code == 404


def test_migration_moves_plans_waivers_and_policies(transactional_db: None) -> None:  # noqa: ARG001
    """0004 forward and back: one plan per customer becomes a subscription, the waiver flag a document."""
    before = [("operations", "0003_fulfilment_rules_resource_types")]
    after = [("operations", "0004_parties_fields_documents")]

    def migrate(target: list[tuple[str, str]]) -> Any:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    apps = migrate(before)
    tid, loc, node = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    offering = apps.get_model("operations", "Offering")
    customer = apps.get_model("operations", "Customer")
    pack = offering.objects.create(tenant_id=tid, kind="plan", name="Pack", price=50, unit="pack", time="none")
    month = offering.objects.create(tenant_id=tid, kind="plan", name="Month", price=90, unit="month", time="none")
    spin = offering.objects.create(tenant_id=tid, kind="class", name="Spin", price=20, unit="session", capacity=8)
    since = date(2026, 1, 5)
    renews = date(2026, 2, 4)
    kw = {"tenant_id": tid, "location_id": loc, "since": since}
    ann = customer.objects.create(name="Ann", plan_offering=pack, plan_credits=3, waiver_signed=True, **kw)
    customer.objects.create(name="Ben", plan_offering=month, plan_renews=renews, **kw)
    customer.objects.create(name="Cal", **kw)
    session = apps.get_model("operations", "Booking").objects.create(
        tenant_id=tid, location_id=loc, offering=spin, start=datetime.now(tz=UTC), end=datetime.now(tz=UTC),
        status="confirmed", price=20,
    )  # fmt: skip
    apps.get_model("operations", "Attendance").objects.create(booking=session, customer=ann)
    apps.get_model("operations", "PolicyOverride").objects.create(
        tenant_id=tid, node_id=node, key="docs.waiver", value=True
    )

    migrate(after)
    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes("operations"))
    subs = {s.customer.name: s for s in Subscription.objects.filter(tenant_id=tid).select_related("customer")}
    assert (subs["Ann"].offering_id, subs["Ann"].credits, subs["Ann"].started) == (pack.id, 3, since)
    assert (subs["Ben"].offering_id, subs["Ben"].renews) == (month.id, renews)
    assert "Cal" not in subs
    assert Attendance.objects.get(booking_id=session.id).subscription_id == subs["Ann"].id
    waivers = Document.objects.filter(tenant_id=tid)
    assert [(d.customer.name, d.type, d.issued, d.expires) for d in waivers] == [("Ann", "waiver", since, None)]
    assert PolicyOverride.objects.get(tenant_id=tid).key == "docs.require.waiver"
    assert PolicyOverride.objects.get(tenant_id=tid).value == "Remind"

    old = migrate(before)
    rows = {c.name: c for c in old.get_model("operations", "Customer").objects.filter(tenant_id=tid)}
    assert (rows["Ann"].plan_offering_id, rows["Ann"].plan_credits, rows["Ann"].waiver_signed) == (pack.id, 3, True)
    assert (rows["Ben"].plan_offering_id, rows["Ben"].plan_renews, rows["Ben"].waiver_signed) == (
        month.id,
        renews,
        False,
    )
    assert rows["Cal"].plan_offering_id is None
    policy = old.get_model("operations", "PolicyOverride").objects.get(tenant_id=tid)
    assert (policy.key, policy.value) == ("docs.waiver", True)
    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes("operations"))


def test_today_warns_about_arrivals_missing_a_reminded_document(tenant: Tenant, calls: Calls) -> None:  # noqa: ARG001
    """Fitness keeps its old behaviour: the waiver is asked for (Remind), flagged on arrival, never blocking."""
    api = Api(tenant.token())
    ids = setup_desk(api, tenant.site_a)
    now = datetime.now(tz=UTC)
    booking = Booking.objects.create(
        tenant_id=tenant.id, location_id=tenant.site_a, offering_id=ids["pt"], customer_id=ids["member"],
        start=now - timedelta(minutes=10), end=now + timedelta(minutes=50), status="confirmed", price=90,
    )  # fmt: skip
    alert = next(a for a in ok(api.get("/today"))["alerts"] if a["id"] == "documents")
    assert alert["title"] == "1 arriving without a valid waiver"
    assert alert["detail"] == "Lena Okafor"
    ok(api.post(f"/customers/{ids['member']}/documents", {"type": "waiver"}))
    assert all(a["id"] != "documents" for a in ok(api.get("/today"))["alerts"])
    assert booking.status == "confirmed"
