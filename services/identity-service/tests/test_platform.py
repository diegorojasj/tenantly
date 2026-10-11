"""Gaps 8-10 in identity: named tree levels, a business's own roles, money and branding settings."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from src.models import Membership, Node, Role, Template

from common.auth import verify

from .test_identity import enter, get, new_business, post, signup

pytestmark = pytest.mark.django_db


def patch(client: Client, path: str, body: dict[str, Any], token: str) -> Any:
    return client.patch(path, body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")


def delete(client: Client, path: str, token: str) -> Any:
    return client.delete(path, HTTP_AUTHORIZATION=f"Bearer {token}")


def join(client: Client, owner_token: str, email: str, role: str, scope_id: str) -> str:
    """Invite `email` as `role` and sign them up with the code; returns their session."""
    invited = post(client, "/tenant/members", {"email": email, "role": role, "scopeId": scope_id}, owner_token)
    assert invited.status_code == 200, invited.content
    body = {
        "name": email.split("@", maxsplit=1)[0],
        "email": email,
        "password": "correct-horse",
        "invite": invited.json()["invite"],
    }
    return post(client, "/auth/signup", body).json()["token"]


def test_templates_name_their_levels_and_the_tree_goes_as_deep_as_they_do() -> None:
    client = Client()
    listed = {t["id"]: t for t in client.get("/templates").json()}
    # The generic template has the single "area" level and the platform's default roles.
    assert listed["general"]["levels"] == [{"key": "area", "label": "Area", "plural": "Areas"}]
    assert [r["id"] for r in listed["general"]["roles"]][:2] == ["owner", "admin"]

    general = Template.objects.get(id="general")
    Template.objects.create(
        id="franchise",
        label="Franchise",
        hue=40,
        terms={**general.terms, "location": "Store", "locations": "Stores"},
        status=general.status,
        transitions=general.transitions,
        levels=[
            {"key": "region", "label": "Region", "plural": "Regions"},
            {"key": "franchisee", "label": "Franchisee", "plural": "Franchisees"},
        ],
        roles=[
            {"id": "owner", "label": "Brand owner", "summary": "", "permissions": ["tenant.manage"]},
            {"id": "franchisee", "label": "Franchisee", "summary": "", "permissions": ["bookings.manage"]},
        ],
        open=480,
        close=1200,
    )
    session = signup(client, "Ana", "ana@example.com")
    created = post(client, "/tenants", {"name": "Burger Co", "templateId": "franchise", "locationName": "HQ"}, session)
    tenant = created.json()
    token = enter(client, session, tenant["slug"])["token"]
    org = next(n for n in verify(token).nodes if n.kind == "org")

    def add(parent: str, kind: str, name: str, level: str | None = None) -> Any:
        body = {"parentId": parent, "kind": kind, "name": name, **({"level": level} if level else {})}
        return post(client, "/tenant/nodes", body, token)

    north = add(org.id, "region", "North")
    assert north.json()["level"] == "region"  # the first level under the business
    acme = add(north.json()["id"], "region", "Acme Foods")
    assert acme.json()["level"] == "franchisee"  # the next one down
    store = add(acme.json()["id"], "location", "Main St")
    assert store.status_code == 200
    # Nothing groups under the last level, groups don't go above their parent, and locations are leaves.
    assert add(acme.json()["id"], "region", "Deeper").status_code == 422
    assert add(acme.json()["id"], "region", "Up", level="region").status_code == 422
    assert add(store.json()["id"], "location", "Inside").status_code == 422
    # Levels may be skipped: a franchisee straight under the business.
    direct = add(org.id, "region", "Solo LLC", level="franchisee")
    assert direct.json()["level"] == "franchisee"

    token = enter(client, session, tenant["slug"])["token"]
    claims = verify(token)
    # Four levels deep, and scope still clamps to the subtree at any depth.
    assert [n.name for n in claims.ancestry(store.json()["id"])] == ["Burger Co", "North", "Acme Foods", "Main St"]
    assert claims.locations(north.json()["id"]) == {store.json()["id"]}
    actions = [e["action"] for e in get(client, "/tenant/audit", token).json()["events"]]
    assert "franchisee.created" in actions
    assert "region.created" in actions

    # The business starts with its template's roles; the owner still holds everything.
    roles = {r["id"]: r for r in get(client, "/tenant/roles", token).json()["roles"]}
    assert set(roles) == {"owner", "franchisee"}
    assert roles["owner"]["label"] == "Brand owner"
    assert "billing.manage" in roles["owner"]["permissions"]


def test_custom_roles_never_grant_more_than_their_maker_holds() -> None:
    client = Client()
    owner_session = signup(client, "Ana", "ana@example.com")
    tenant = new_business(client, owner_session)
    owner = enter(client, owner_session, tenant["slug"])["token"]
    org = next(n for n in verify(owner).nodes if n.kind == "org")

    listed = get(client, "/tenant/roles", owner).json()
    assert [r["id"] for r in listed["roles"]] == [
        "owner",
        "admin",
        "regional_manager",
        "location_manager",
        "analyst",
        "auditor",
    ]
    assert listed["canEdit"] is True
    assert next(r for r in listed["roles"] if r["id"] == "owner")["members"] == 1

    made = post(
        client,
        "/tenant/roles",
        {"label": "Night desk", "summary": "Evenings only", "permissions": ["bookings.manage", "payments.collect"]},
        owner,
    )
    assert made.status_code == 200, made.content
    assert made.json() == {
        "id": "night_desk",
        "label": "Night desk",
        "summary": "Evenings only",
        "permissions": ["bookings.manage", "payments.collect"],
        "builtin": False,
        "members": 0,
    }
    assert post(client, "/tenant/roles", {"label": "night desk"}, owner).status_code == 409
    assert post(client, "/tenant/roles", {"label": "Bad", "permissions": ["root"]}, owner).status_code == 422

    # Someone holding the custom role gets exactly its permissions.
    lee = join(client, owner, "lee@example.com", "night_desk", org.id)
    lee_claims = verify(enter(client, lee, tenant["slug"])["token"])
    assert lee_claims.permissions == ("bookings.manage", "payments.collect")
    assert next(w for w in get(client, "/me/workspaces", lee).json())["roleLabel"] == "Night desk"

    # An area manager may make and hand out roles within their own permissions only.
    raj = join(client, owner, "raj@example.com", "regional_manager", org.id)
    Role.objects.filter(key="regional_manager").update(
        permissions=[*Role.objects.get(key="regional_manager").permissions, "roles.assign"]
    )
    manager = enter(client, raj, tenant["slug"])["token"]
    too_much = post(client, "/tenant/roles", {"label": "Boss", "permissions": ["billing.manage"]}, manager)
    assert too_much.status_code == 403
    small = post(client, "/tenant/roles", {"label": "Greeter", "permissions": ["bookings.manage"]}, manager)
    assert small.status_code == 200
    assert patch(client, "/tenant/roles/greeter", {"permissions": ["tenant.manage"]}, manager).status_code == 403
    # Roles stronger than theirs, their own role and the owner role are out of reach.
    assert patch(client, "/tenant/roles/admin", {"label": "Admins"}, manager).status_code == 403
    assert patch(client, "/tenant/roles/regional_manager", {"permissions": []}, manager).status_code == 403
    assert delete(client, "/tenant/roles/owner", owner).status_code == 403
    assert patch(client, "/tenant/roles/owner", {"label": "Boss"}, owner).status_code == 403

    # The owner edits a role; holders get the new permissions on their next token.
    edited = patch(client, "/tenant/roles/night_desk", {"permissions": ["bookings.manage"]}, owner)
    assert edited.json()["members"] == 1
    assert verify(enter(client, lee, tenant["slug"])["token"]).permissions == ("bookings.manage",)
    # A role someone holds can't be removed; an unused one can.
    assert delete(client, "/tenant/roles/night_desk", owner).status_code == 409
    assert delete(client, "/tenant/roles/greeter", owner).status_code == 200
    assert (
        post(
            client, "/tenant/members", {"email": "x@example.com", "role": "greeter", "scopeId": org.id}, owner
        ).status_code
        == 422
    )

    trail = [e["action"] for e in get(client, "/tenant/audit", owner).json()["events"]]
    assert {"role.created", "role.updated", "role.deleted"} <= set(trail)


def test_money_and_branding_settings_travel_with_the_tenant() -> None:
    client = Client()
    owner_session = signup(client, "Ana", "ana@example.com")
    tenant = new_business(client, owner_session)
    assert (tenant["currency"], tenant["taxRate"], tenant["pricesIncludeTax"]) == ("USD", "0.00", True)
    owner = enter(client, owner_session, tenant["slug"])["token"]
    assert verify(owner).money["currency"] == "USD"

    saved = patch(
        client,
        "/tenant/settings",
        {
            "currency": "eur",
            "taxRate": "21.00",
            "taxLabel": "IVA",
            "pricesIncludeTax": False,
            "logoUrl": "https://cdn.example.com/logo.svg",
            "customDomain": "Book.Ironworks.example",
        },
        owner,
    )
    assert saved.status_code == 200, saved.content
    assert saved.json()["money"] == {
        "currency": "EUR",
        "taxRate": "21.00",
        "taxLabel": "IVA",
        "pricesIncludeTax": False,
    }
    assert saved.json()["branding"] == {
        "logoUrl": "https://cdn.example.com/logo.svg",
        "customDomain": "book.ironworks.example",
    }

    entered = enter(client, owner_session, tenant["slug"])
    assert verify(entered["token"]).money == {
        "currency": "EUR",
        "taxRate": "21.00",
        "taxLabel": "IVA",
        "pricesIncludeTax": False,
    }
    assert verify(entered["token"]).currency == "EUR"
    assert entered["context"]["tenant"]["logoUrl"] == "https://cdn.example.com/logo.svg"

    bad = (
        {"currency": "XYZ"},
        {"taxRate": "120"},
        {"logoUrl": "http://insecure.example/logo.png"},
        {"customDomain": "not a domain"},
    )
    for body in bad:
        assert patch(client, "/tenant/settings", body, owner).status_code == 422, body

    # A domain belongs to one business only.
    other_session = signup(client, "Bo", "bo@example.com")
    other = new_business(client, other_session, "Other Gym")
    other_token = enter(client, other_session, other["slug"])["token"]
    assert patch(client, "/tenant/settings", {"customDomain": "book.ironworks.example"}, other_token).status_code == 409

    # SSO is a placeholder: stored, validated, never active.
    assert patch(client, "/tenant/settings", {"sso": {"protocol": "saml"}}, owner).status_code == 422
    sso = patch(
        client,
        "/tenant/settings",
        {"sso": {"protocol": "oidc", "issuer": "https://login.example.com", "clientId": "tenantly"}},
        owner,
    ).json()["sso"]
    assert sso == {
        "protocol": "oidc",
        "issuer": "https://login.example.com",
        "metadataUrl": "",
        "clientId": "tenantly",
        "enforced": False,
        "status": "not_connected",
    }
    assert entered["context"]["tenant"]["idp"] == "Email & password"
    categories = {
        e["category"] for e in get(client, "/tenant/audit", owner).json()["events"] if e["action"] == "tenant.updated"
    }
    assert categories == {"billing", "config", "security"}

    # Only roles that manage the business see or change these settings.
    org = next(n for n in verify(owner).nodes if n.kind == "org")
    admin = enter(client, join(client, owner, "ad@example.com", "admin", org.id), tenant["slug"])["token"]
    assert get(client, "/tenant/settings", admin).status_code == 403
    assert patch(client, "/tenant/settings", {"currency": "USD"}, admin).status_code == 403


def test_billing_reads_the_plan_and_tenantly_sets_a_custom_one() -> None:
    client = Client()
    session = signup(client, "Ana", "ana@example.com")
    tenant = new_business(client, session)
    path = f"/internal/tenants/{tenant['id']}/plan"
    internal = {"HTTP_X_INTERNAL_TOKEN": "test-internal-token"}
    assert client.get(path).status_code == 401
    assert client.get(path, **internal).json() == {"plan": "Starter", "terms": None}

    def put(body: dict[str, Any]) -> Any:
        return client.put(path, body, content_type="application/json", **internal)

    # Custom needs its terms, and only Custom takes them.
    assert put({"plan": "Custom"}).status_code == 422
    assert put({"plan": "Growth", "terms": {"price": "10"}}).status_code == 422
    custom = put({"plan": "Custom", "terms": {"price": "250", "customerLimit": 1000}})
    assert custom.json() == {
        "plan": "Custom",
        "terms": {"price": "250", "customerLimit": 1000, "paymentLimit": None},
    }
    assert client.get(path, **internal).json()["plan"] == "Custom"
    assert put({"plan": "Growth"}).json() == {"plan": "Growth", "terms": None}


@pytest.mark.django_db(transaction=True)
def test_levels_and_roles_migration_round_trips() -> None:
    """0009 forward and back: groups land on "area", every business gets the six roles, and back."""
    before = [("identity", "0008_tree_levels_roles_money_branding")]
    after = [("identity", "0009_seed_levels_and_roles")]

    def migrate(target: list[tuple[str, str]]) -> Any:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    old = migrate(before)
    # Transactional tests flush the seeded rows, so bring a template of our own.
    old.get_model("identity", "Template").objects.create(id="gym", label="Gym", hue=1, open=360, close=1260)
    tenant = old.get_model("identity", "Tenant").objects.create(
        slug="old", name="Old Gym", template_id="gym", hue=1, tenant_key="tk_old"
    )
    node_model = old.get_model("identity", "Node")
    org = node_model.objects.create(tenant=tenant, kind="org", name="Old Gym", code="OG")
    node_model.objects.create(tenant=tenant, parent=org, kind="region", name="North", code="NO01")
    versions = {t.id: t.version for t in old.get_model("identity", "Template").objects.all()}

    new = migrate(after)
    assert new.get_model("identity", "Node").objects.get(name="North").level == "area"
    keys = set(new.get_model("identity", "Role").objects.filter(tenant_id=tenant.id).values_list("key", flat=True))
    assert keys == {"owner", "admin", "regional_manager", "location_manager", "analyst", "auditor"}
    gym = new.get_model("identity", "Template").objects.get(id="gym")
    assert gym.version == versions["gym"] + 1
    assert gym.levels[0]["key"] == "area"
    assert next(r["id"] for r in gym.roles) == "owner"

    back = migrate(before)
    assert back.get_model("identity", "Node").objects.get(name="North").level == ""
    assert not back.get_model("identity", "Role").objects.exists()
    assert {t.id: t.version for t in back.get_model("identity", "Template").objects.all()} == versions
    migrate(after)
    assert Node.objects.filter(level="area").exists()
    assert Membership.objects.count() == 0
