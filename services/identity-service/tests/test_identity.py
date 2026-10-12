"""Identity end to end: accounts, creating a business, entering it, team, tree, audit."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from src.models import Template, User
from src.services import accounts, tenants

from common.auth import verify
from common.errors import ConflictError, InvalidError

pytestmark = pytest.mark.django_db


def post(client: Client, path: str, body: dict[str, Any], token: str | None = None) -> Any:
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return client.post(path, body, content_type="application/json", **headers)


def get(client: Client, path: str, token: str) -> Any:
    return client.get(path, HTTP_AUTHORIZATION=f"Bearer {token}")


def account(client: Client, name: str, email: str) -> str:
    """An account as a Tenantly admin or an owner would create it, signed in; returns its session."""
    accounts.create_account(name, email, "correct-horse")
    response = post(client, "/auth/login", {"email": email, "password": "correct-horse"})
    assert response.status_code == 200, response.content
    return response.json()["token"]


def new_business(
    client: Client,
    session: str,
    name: str = "Ironworks Gym",
    template_id: str = "general",
    location: str = "Union Square",
) -> dict[str, Any]:
    """A business opened for the signed-in owner, as the admin console does."""
    owner = User.objects.get(id=get(client, "/me", session).json()["id"])
    tenant = tenants.create_tenant(owner, name=name, industry="Gym", location_name=location, template_id=template_id)
    return tenants.tenant_dict(tenant)


def enter(client: Client, session: str, slug: str, scope: str | None = None) -> dict[str, Any]:
    response = post(client, f"/tenants/{slug}/token", {"scope": scope}, session)
    assert response.status_code == 200, response.content
    return response.json()


def test_nobody_signs_up_and_sign_in_errors_read_for_people() -> None:
    client = Client()
    body = {"name": "Ana", "email": "ana@example.com", "password": "12345678"}
    # Accounts and businesses come from a Tenantly admin or a business's owner, never the public.
    assert post(client, "/auth/signup", body).status_code == 404
    account(client, "Ana Solís", "Ana@Example.com")
    session = post(client, "/auth/login", {"email": "ana@example.com", "password": "correct-horse"}).json()["token"]
    assert post(client, "/tenants", {"name": "Mine", "locationName": "Main"}, session).status_code in {404, 405}
    with pytest.raises(ConflictError, match="already exists"):
        accounts.create_account("Ana", "ana@example.com", "12345678")
    wrong = post(client, "/auth/login", {"email": "ana@example.com", "password": "nope-nope"})
    assert wrong.status_code == 401
    ok = post(client, "/auth/login", {"email": "ANA@example.com", "password": "correct-horse"})
    assert ok.json()["user"]["name"] == "Ana Solís"


def test_a_new_business_starts_empty_with_its_owner_and_first_location() -> None:
    client = Client()
    session = account(client, "Ana Solís", "ana@example.com")
    assert get(client, "/me/workspaces", session).json() == []
    tenant = new_business(client, session)
    assert tenant["template"]["terms"]["customers"] == "Customers"
    workspaces = get(client, "/me/workspaces", session).json()
    assert [w["role"] for w in workspaces] == ["owner"]

    entered = enter(client, session, tenant["slug"])
    claims = verify(entered["token"])
    assert claims.tenant_id == tenant["id"]
    assert claims.can("billing.manage")
    kinds = sorted(n["kind"] for n in entered["context"]["nodes"])
    assert kinds == ["location", "org"]


def test_outsiders_are_refused_and_invites_need_their_code() -> None:
    client = Client()
    owner = account(client, "Ana", "ana@example.com")
    tenant = new_business(client, owner)
    outsider = account(client, "Eve", "eve@example.com")
    refused = post(client, f"/tenants/{tenant['slug']}/token", {}, outsider)
    assert refused.status_code == 403

    token = enter(client, owner, tenant["slug"])
    location = next(n for n in token["context"]["nodes"] if n["kind"] == "location")
    account(client, "Priya", "priya@example.com")
    invited = post(
        client,
        "/tenant/members",
        {"email": "priya@example.com", "role": "location_manager", "scopeId": location["id"]},
        token["token"],
    )
    assert invited.status_code == 200, invited.content
    code = invited.json()["invite"]
    pending = get(client, "/tenant/members", token["token"]).json()
    assert {m["status"] for m in pending["direct"]} == {"active", "invited"}

    # Holding an account with that address isn't enough: joining takes the code.
    squatter = post(client, "/auth/login", {"email": "priya@example.com", "password": "correct-horse"}).json()["token"]
    assert post(client, f"/tenants/{tenant['slug']}/token", {}, squatter).status_code == 403
    # Someone else holding the code can't redeem it either: it was sent to Priya's address.
    assert post(client, "/me/invites", {"invite": code}, outsider).json() == {"joined": False}

    priya = post(
        client, "/auth/login", {"email": "priya@example.com", "password": "correct-horse", "invite": code}
    ).json()["token"]
    priya_token = enter(client, priya, tenant["slug"])
    claims = verify(priya_token["token"])
    assert claims.role == "location_manager"
    assert claims.home_scope_id == location["id"]
    # A scope outside her assignment falls back to her home scope.
    widened = enter(client, priya, tenant["slug"], scope=claims.nodes[0].id if claims.nodes[0].kind == "org" else None)
    assert widened["context"]["scopeId"] == location["id"]
    # The code is single use.
    assert post(client, "/me/invites", {"invite": code}, priya).json() == {"joined": False}


def test_nobody_grants_more_than_their_own_role() -> None:
    client = Client()
    owner = account(client, "Ana", "ana@example.com")
    tenant = new_business(client, owner)
    token = enter(client, owner, tenant["slug"])
    org = next(n for n in token["context"]["nodes"] if n["kind"] == "org")
    created = post(
        client,
        "/tenant/members",
        {
            "email": "raj@example.com",
            "role": "regional_manager",
            "scopeId": org["id"],
            "name": "Raj",
            "password": "correct-horse",
        },
        token["token"],
    )
    assert created.status_code == 200, created.content
    raj = post(client, "/auth/login", {"email": "raj@example.com", "password": "correct-horse"}).json()["token"]
    manager = enter(client, raj, tenant["slug"])["token"]
    escalate = post(
        client, "/tenant/members", {"email": "raj2@example.com", "role": "admin", "scopeId": org["id"]}, manager
    )
    assert escalate.status_code == 403
    account(client, "Lee", "lee@example.com")
    peer = post(
        client,
        "/tenant/members",
        {"email": "lee@example.com", "role": "location_manager", "scopeId": org["id"]},
        manager,
    )
    assert peer.status_code == 200, peer.content


def test_tree_changes_are_audited_on_an_intact_chain() -> None:
    client = Client()
    owner = account(client, "Ana", "ana@example.com")
    tenant = new_business(client, owner)
    token = enter(client, owner, tenant["slug"])
    org = next(n for n in token["context"]["nodes"] if n["kind"] == "org")
    area = post(client, "/tenant/nodes", {"parentId": org["id"], "kind": "region", "name": "Brooklyn"}, token["token"])
    assert area.status_code == 200, area.content
    nested = post(
        client,
        "/tenant/nodes",
        {"parentId": area.json()["id"], "kind": "location", "name": "Park Slope"},
        token["token"],
    )
    assert nested.status_code == 200
    bad = post(client, "/tenant/nodes", {"parentId": area.json()["id"], "kind": "region", "name": "X"}, token["token"])
    assert bad.status_code == 422

    trail = get(client, "/tenant/audit", token["token"]).json()
    assert trail["chain"]["intact"] is True
    assert trail["chain"]["length"] == 4  # business, first location, area, location
    assert trail["events"][0]["action"] == "location.created"


def test_internal_audit_requires_the_internal_token() -> None:
    client = Client()
    owner = account(client, "Ana", "ana@example.com")
    tenant = new_business(client, owner)
    body = {
        "tenantId": tenant["id"],
        "actorId": "u1",
        "actorName": "Ana",
        "action": "booking.created",
        "category": "config",
        "target": "Spin 45",
        "scopeId": None,
    }
    assert client.post("/internal/audit", body, content_type="application/json").status_code == 401
    ok = client.post(
        "/internal/audit",
        body,
        content_type="application/json",
        HTTP_X_INTERNAL_TOKEN="test-internal-token",  # noqa: S106
    )
    assert ok.status_code == 200


def test_templates_are_stored_data_and_travel_in_the_tenant_token() -> None:
    client = Client()
    listed = {t["id"]: t for t in client.get("/templates").json()}
    # One generic template: no vertical to pick, every preset available.
    assert set(listed) == {"general"}
    general = listed["general"]
    assert [p["key"] for p in general["presets"]] == ["appointment", "class", "rental", "visit", "plan"]
    assert general["transitions"]["confirmed"] == ["checked_in", "no_show", "cancelled"]
    assert (general["terms"]["customer"], general["terms"]["booking"]) == ("Customer", "Booking")
    # Documents are available but off until a business turns them on in Policies.
    assert general["documents"] == [{"key": "waiver", "label": "Waiver", "appliesTo": "customer", "validDays": None}]
    assert general["policyDefaults"] == {"docs.require.waiver": "Not needed"}
    assert general["fields"] == {}
    assert [a["key"] for a in general["accountTypes"]] == ["business", "household"]
    assert general["subjectTypes"] == []
    rental = next(p for p in general["presets"] if p["key"] == "rental")
    assert (rental["capacity"], rental["time"], rental["units"][0]) == (1, "window", "hour")
    assert rental["requires"] == [{"type": "asset", "quantity": 1, "pick": False, "named": True}]
    assert next(p for p in general["presets"] if p["key"] == "visit")["place"] == "at_customer"
    assert [(r["key"], r["people"]) for r in general["resourceTypes"]] == [("staff", True), ("asset", False)]

    Template.objects.create(
        id="clinic",
        label="Clinic",
        hue=20,
        presets=[
            {
                "key": "checkup",
                "label": "Check-up",
                "capacity": 1,
                "time": "slot",
                "units": ["session"],
                "place": "on_site",
                "requires": [
                    {"type": "staff", "quantity": 1, "role": "Dentist"},
                    {"type": "chair", "quantity": 1},
                ],
            }
        ],
        resource_types=[
            {"key": "staff", "label": "Dentist", "plural": "Dentists", "people": True},
            {"key": "chair", "label": "Chair", "plural": "Chairs", "people": False},
        ],
        terms={**general["terms"], "customer": "Patient", "location": "Practice", "chair": "Chair"},
        status=general["status"],
        transitions={"requested": ["confirmed"], "confirmed": ["completed"], "completed": []},
        fields={"customer": [{"key": "insurer", "label": "Insurer", "type": "text", "pii": True}]},
        subject_types=[{"key": "child", "label": "Child", "plural": "Children", "fields": []}],
        open=9 * 60,
        close=17 * 60,
        policy_defaults={"booking.approval": True},
    )
    session = account(client, "Ana Solís", "ana@example.com")
    with pytest.raises(InvalidError):
        new_business(client, session, "Nope", template_id="bakery", location="Main")
    with pytest.raises(InvalidError, match="Name your first practice"):
        new_business(client, session, "Smile Co", template_id="clinic", location="X")
    tenant = new_business(client, session, "Smile Co", template_id="clinic", location="Main")
    assert tenant["template"]["terms"]["chair"] == "Chair"
    assert tenant["hue"] == 20

    entered = enter(client, session, tenant["slug"])
    claims = verify(entered["token"])
    assert claims.template_id == "clinic"
    assert claims.moves("confirmed") == ["completed"]
    assert claims.template["policyDefaults"] == {"booking.approval": True}
    assert "description" not in claims.template
    assert claims.template["presets"][0]["requires"][1] == {"type": "chair", "quantity": 1}
    assert claims.template["resourceTypes"][1]["key"] == "chair"
    assert claims.template["fields"]["customer"][0]["pii"] is True
    assert claims.template["subjectTypes"][0]["key"] == "child"
    assert entered["context"]["tenant"]["template"]["transitions"]["requested"] == ["confirmed"]


def test_a_location_keeps_its_own_time_zone_and_hours_in_the_token() -> None:
    client = Client()
    owner = account(client, "Ana", "ana@example.com")
    tenant = new_business(client, owner)
    token = enter(client, owner, tenant["slug"])["token"]
    claims = verify(token)
    location = next(n for n in claims.nodes if n.kind == "location")
    org = next(n for n in claims.nodes if n.kind == "org")
    assert (location.tz, location.hours) == ("UTC", None)  # defaults: the template's hours, UTC
    assert claims.hours(location.id) == (8 * 60, 20 * 60)

    def patch(node_id: str, body: dict[str, Any]) -> Any:
        return client.patch(
            f"/tenant/nodes/{node_id}", body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}"
        )

    assert patch(location.id, {"tz": "Mars/Olympus"}).status_code == 422
    assert patch(org.id, {"tz": "Europe/Lisbon"}).status_code == 422  # only locations keep a clock
    assert patch(location.id, {"open": 600, "close": 540}).status_code == 422
    saved = patch(location.id, {"tz": "America/New_York", "open": 9 * 60, "close": 17 * 60})
    assert saved.status_code == 200, saved.content
    assert saved.json()["tz"] == "America/New_York"
    assert saved.json()["hours"] == [540, 1020]

    claims = verify(enter(client, owner, tenant["slug"])["token"])
    assert claims.zone(location.id).key == "America/New_York"
    assert claims.hours(location.id) == (540, 1020)
    assert claims.node(org.id).tz == "UTC"  # untouched nodes still travel as four-item rows

    assert patch(location.id, {"resetHours": True}).status_code == 200
    assert verify(enter(client, owner, tenant["slug"])["token"]).hours(location.id) == (8 * 60, 20 * 60)


def test_a_location_has_an_address_and_a_pin_on_the_map() -> None:
    client = Client()
    owner = account(client, "Ana", "ana@example.com")
    tenant = new_business(client, owner)
    entered = enter(client, owner, tenant["slug"])
    token = entered["token"]
    location = next(n for n in entered["context"]["nodes"] if n["kind"] == "location")
    org = next(n for n in entered["context"]["nodes"] if n["kind"] == "org")
    assert (location["address"], location["pin"]) == ("", None)  # not on the map until someone places it

    def patch(node_id: str, body: dict[str, Any]) -> Any:
        return client.patch(
            f"/tenant/nodes/{node_id}", body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}"
        )

    assert patch(org["id"], {"lat": 40.7, "lng": -74.0}).status_code == 422  # only locations sit on the map
    assert patch(location["id"], {"lat": 91, "lng": 0}).status_code == 422
    saved = patch(location["id"], {"address": " 15 W 18th St, New York ", "lat": 40.7387, "lng": -73.9926})
    assert saved.status_code == 200, saved.content
    assert saved.json()["address"] == "15 W 18th St, New York"
    assert saved.json()["pin"] == [40.7387, -73.9926]

    cleared = patch(location["id"], {"clearPin": True})
    assert (cleared.json()["address"], cleared.json()["pin"]) == ("15 W 18th St, New York", None)


@pytest.mark.django_db(transaction=True)
def test_template_migration_types_fields_and_turns_the_waiver_into_a_document() -> None:
    """0007 forward and back: customer fields, the waiver flag and its policy default survive a round trip."""
    before = [("identity", "0006_template_presets_resource_types")]
    after = [("identity", "0007_template_parties_fields_documents")]

    def migrate(target: list[tuple[str, str]]) -> Any:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps.get_model("identity", "Template")

    old = migrate(before)
    original = {t.id: (t.customer_fields, t.waiver, t.policy_defaults) for t in old.objects.all()}
    old.objects.create(
        id="spa",
        label="Spa",
        hue=10,
        open=540,
        close=1200,
        customer_fields=[{"key": "allergies", "label": "Allergies"}],
        waiver=True,
        policy_defaults={"docs.waiver": True, "booking.window": 30},
    )
    new = migrate(after)
    spa = new.objects.get(id="spa")
    assert spa.fields == {"customer": [{"key": "allergies", "label": "Allergies", "type": "text"}]}
    assert spa.documents == [{"key": "waiver", "label": "Waiver", "appliesTo": "customer", "validDays": None}]
    assert spa.policy_defaults == {"docs.require.waiver": "Remind", "booking.window": 30}
    assert (spa.account_types, spa.subject_types) == ([], [])

    back = migrate(before)
    assert back.objects.get(id="spa").policy_defaults == {"docs.waiver": True, "booking.window": 30}
    assert {t.id: (t.customer_fields, t.waiver, t.policy_defaults) for t in back.objects.exclude(id="spa")} == original
    migrate(after)


def test_people_read_errors_and_labels_in_their_language() -> None:
    client = Client()
    session = account(client, "Ana Solís", "ana@example.com")
    spanish = {"HTTP_ACCEPT_LANGUAGE": "es"}
    wrong = client.post(
        "/auth/login",
        {"email": "ana@example.com", "password": "nope-nope"},
        content_type="application/json",
        **spanish,
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "El correo o la contraseña no son correctos"
    # Shared errors (common/) are translated too.
    expired = client.get("/tenant/roles", HTTP_AUTHORIZATION="Bearer nope", **spanish)
    assert expired.json()["detail"] == "Tu sesión expiró — vuelve a iniciar sesión"

    owner = enter(client, session, new_business(client, session)["slug"])["token"]
    roles = client.get("/tenant/roles", HTTP_AUTHORIZATION=f"Bearer {owner}", **spanish).json()
    assert dict(roles["permissions"])["roles.assign"] == "Asignar roles"
    assert roles["roles"][0]["label"] == "Propietario"
    assert get(client, "/tenant/roles", owner).json()["permissions"][4] == ["roles.assign", "Assign roles"]
