"""The Tenantly admin console: separate admin accounts with time-boxed access windows, tokens
that never cross with tenant ones, an append-only audit log, owners (never employees) and
their status, and billing work forwarded signed by the admin."""

# The `billing` fixture is sometimes requested only for its effect.
# ruff: noqa: ARG001

from __future__ import annotations

import io
import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from src.models import AdminAuditEvent, AuditEvent, PlatformAdmin, Session, Tenant, User
from src.services import admins

from common.auth import verify
from common.errors import UnauthenticatedError
from common.internal import use_transport

from .test_identity import account, enter, get, new_business, post
from .test_platform import join

pytestmark = pytest.mark.django_db

PASSWORD = "staff-horse-battery"  # noqa: S105
NEW_PASSWORD = "staff-horse-battery-2"  # noqa: S105


def put(client: Client, path: str, body: dict[str, Any], token: str) -> Any:
    return client.put(path, body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")


def make_admin(email: str = "staff@tenantly.dev") -> PlatformAdmin:
    call_command("create_admin", email, "--name", "Dana Staff", "--password", PASSWORD, stdout=io.StringIO())
    return PlatformAdmin.objects.get(email=email)


def admin_login(client: Client, email: str = "staff@tenantly.dev") -> Any:
    return post(client, "/admin/auth/login", {"email": email, "password": PASSWORD})


def admin_token(client: Client, email: str = "staff@tenantly.dev") -> str:
    if not PlatformAdmin.objects.filter(email=email).exists():
        make_admin(email)
    response = admin_login(client, email)
    assert response.status_code == 200, response.content
    return response.json()["token"]


class Clock:
    def __init__(self) -> None:
        self.shift = timedelta(0)

    def __call__(self) -> Any:
        return admins.timezone.now() + self.shift


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """The admin clock, moved forward by the test."""
    c = Clock()
    monkeypatch.setattr(admins, "now", c)
    return c


@pytest.fixture
def billing() -> list[tuple[str, str, dict[str, Any]]]:
    """Billing as identity sees it: summaries, and a before/after for every admin change."""
    sent: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        body = json.loads(request.content) if request.content else {}
        sent.append((request.method, request.url.path, body))
        path = request.url.path
        if path == "/internal/admin/summaries":
            line = {"plan": "Starter", "currency": "USD", "price": "29.00", "status": "active", "used": 3}
            return httpx.Response(200, json=dict.fromkeys(body["tenantIds"], line))
        if path.endswith("/subscription"):
            return httpx.Response(404, json={"detail": "This business has no Tenantly subscription yet"})
        if path.endswith("/plan"):
            before = {"plan": "Starter", "version": 2, "status": "active"}
            return httpx.Response(200, json={"plan": "Custom", "status": "active", "before": before})
        if path.endswith("/paid"):
            return httpx.Response(200, json={"id": "x", "status": "paid", "before": {"status": "open"}})
        if path.endswith("/reprice"):
            return httpx.Response(
                200, json={"before": {"price": "29.00"}, "after": {"id": "v3", "price": "35.00"}, "scheduled": 4}
            )
        if path == "/internal/admin/policy" and request.method == "PUT":
            return httpx.Response(200, json={"before": {"version": 1}, "after": {"version": 2}})
        return httpx.Response(200, json={"ok": True})

    use_transport(httpx.MockTransport(handler))
    yield sent
    use_transport(None)


# ------------------------------------------------------------- accounts --


def test_create_admin_makes_a_separate_account_with_a_ten_minute_window_and_a_password_shown_once() -> None:
    out = io.StringIO()
    call_command("create_admin", "Root@Tenantly.dev", "--name", "Root", stdout=out)
    password = out.getvalue().split("password (shown once): ")[1].strip()
    assert len(password) >= 20
    admin = PlatformAdmin.objects.get(email="root@tenantly.dev")
    assert admin.password_hash != password
    assert admin.status == "active"
    assert admin.active_until - admin.activated_at == timedelta(minutes=10)
    assert admin.activated_by.startswith("cli:")
    assert not User.objects.filter(email="root@tenantly.dev").exists()  # not a tenant account
    assert [e.kind for e in AdminAuditEvent.objects.order_by("id")] == ["created", "activated"]

    client = Client()
    login = post(client, "/admin/auth/login", {"email": "root@tenantly.dev", "password": password})
    assert login.status_code == 200, login.content
    assert 590 <= login.json()["admin"]["remainingSeconds"] <= 600
    # It is no tenant account: the tenant sign-in doesn't know it.
    assert post(client, "/auth/login", {"email": "root@tenantly.dev", "password": password}).status_code == 401

    with pytest.raises(CommandError, match="already"):
        call_command("create_admin", "root@tenantly.dev", "--name", "Root", stdout=io.StringIO())
    with pytest.raises(CommandError):
        call_command("create_admin", "new@tenantly.dev", "--name", "New", "--password", "short", stdout=io.StringIO())
    call_command("create_admin", "later@tenantly.dev", "--name", "Later", "--dormant", stdout=io.StringIO())
    assert PlatformAdmin.objects.get(email="later@tenantly.dev").status == "dormant"
    assert admin_login(client, "later@tenantly.dev").status_code == 401

    # Activating it later replaces the password too: a generated one, shown once.
    out = io.StringIO()
    call_command("activate_admin", "later@tenantly.dev", stdout=out)
    renewed = out.getvalue().split("new password (shown once): ")[1].strip()
    assert len(renewed) >= 20
    assert admin_login(client, "later@tenantly.dev").status_code == 401
    assert post(client, "/admin/auth/login", {"email": "later@tenantly.dev", "password": renewed}).status_code == 200


def test_admins_and_their_log_are_never_deleted_or_rewritten() -> None:
    admin = make_admin()
    with pytest.raises(PermissionError):
        admin.delete()
    with pytest.raises(PermissionError):
        PlatformAdmin.objects.all().delete()
    event = AdminAuditEvent.objects.first()
    with pytest.raises(PermissionError):
        event.delete()
    with pytest.raises(PermissionError):
        AdminAuditEvent.objects.all().delete()
    event.action = "rewritten"
    with pytest.raises(PermissionError):
        event.save()
    call_command("block_admin", admin.email, stdout=io.StringIO())
    assert PlatformAdmin.objects.filter(id=admin.id, status="blocked").exists()  # blocked, still there


# ---------------------------------------------------------------- windows --


def test_a_closed_window_refuses_sign_in_and_every_request_until_reopened_from_the_server(
    clock: Clock, billing: list[Any]
) -> None:
    client = Client()
    token = admin_token(client)
    assert get(client, "/admin/owners", token).status_code == 200
    me = get(client, "/admin/me", token).json()
    assert me["email"] == "staff@tenantly.dev"

    # Ten minutes on: the token is still signed, but the window is closed.
    clock.shift = timedelta(minutes=10)
    refused = get(client, "/admin/owners", token)
    assert refused.status_code == 401
    assert refused.json()["detail"] == "Your admin access has ended"
    admin = PlatformAdmin.objects.get(email="staff@tenantly.dev")
    assert admin.status == "blocked"  # flipped on the spot, no sweep needed
    expired = AdminAuditEvent.objects.get(kind="expired")
    assert (expired.before["status"], expired.after["status"]) == ("active", "blocked")
    denied = admin_login(client)
    assert (denied.status_code, denied.json()["detail"]) == (401, "Your admin access has ended")
    assert AdminAuditEvent.objects.filter(kind="login_denied", action="window_closed").count() == 1
    # Nothing was forwarded with a closed window.
    calls = len(billing)
    assert (
        post(client, "/admin/invoices/8a0e2a52-3a43-4f6f-9b7e-0f6f3b8d2a11/paid", {"reference": "x"}, token).status_code
        == 401
    )
    assert len(billing) == calls

    # Only the server reopens it, with a new password; tokens from the earlier window stay void.
    with pytest.raises(CommandError, match="different"):
        call_command("activate_admin", "staff@tenantly.dev", "--password", PASSWORD, stdout=io.StringIO())
    call_command("activate_admin", "staff@tenantly.dev", "--password", NEW_PASSWORD, stdout=io.StringIO())
    assert get(client, "/admin/owners", token).status_code == 401
    assert admin_login(client).status_code == 401  # the old password is gone
    fresh = post(client, "/admin/auth/login", {"email": "staff@tenantly.dev", "password": NEW_PASSWORD})
    assert fresh.status_code == 200
    assert get(client, "/admin/owners", fresh.json()["token"]).status_code == 200

    # Blocking ends it now.
    call_command("block_admin", "staff@tenantly.dev", stdout=io.StringIO())
    assert get(client, "/admin/owners", fresh.json()["token"]).status_code == 401
    kinds = list(AdminAuditEvent.objects.order_by("id").values_list("kind", flat=True))
    assert kinds == [
        "created",
        "activated",
        "login",
        "expired",
        "login_denied",
        "activated",
        "login_denied",
        "login",
        "blocked",
    ]
    assert set(AdminAuditEvent.objects.filter(kind="activated").values_list("action", flat=True)) == {"new_password"}


def test_wrong_passwords_and_unknown_emails_are_logged_and_read_the_same() -> None:
    make_admin()
    client = Client()
    wrong = post(client, "/admin/auth/login", {"email": "staff@tenantly.dev", "password": "nope-nope-nope"})
    unknown = post(client, "/admin/auth/login", {"email": "who@tenantly.dev", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    denied = AdminAuditEvent.objects.filter(kind="login_denied").order_by("id")
    assert [(e.action, e.admin_id is None) for e in denied] == [("wrong_password", False), ("unknown_email", True)]


def test_the_sweep_blocks_overdue_admins(clock: Clock) -> None:
    make_admin()
    make_admin("other@tenantly.dev")
    clock.shift = timedelta(minutes=11)
    out = io.StringIO()
    call_command("expire_admins", stdout=out)
    assert "expired=2" in out.getvalue()
    assert set(PlatformAdmin.objects.values_list("status", flat=True)) == {"blocked"}
    call_command("expire_admins", stdout=io.StringIO())
    assert AdminAuditEvent.objects.filter(kind="expired").count() == 2  # once each


# ------------------------------------------------------------- separation --


def test_tenant_credentials_never_open_admin_routes_and_admin_tokens_open_nothing_else(billing: list[Any]) -> None:
    client = Client()
    owner = account(client, "Ana", "ana@example.com")
    gym = new_business(client, owner)
    tenant_token = enter(client, owner, gym["slug"])["token"]
    staff = admin_token(client)

    for bearer in (owner, tenant_token, "garbage"):
        refused = get(client, "/admin/owners", bearer)
        assert refused.status_code == 401, bearer
    assert client.get("/admin/owners").status_code == 401
    # The admin token is no session and no tenant token.
    assert get(client, "/me", staff).status_code == 401
    assert get(client, "/tenant/members", staff).status_code == 401
    with pytest.raises(UnauthenticatedError):
        verify(staff)


# ----------------------------------------------------------------- owners --


def test_owners_are_listed_with_their_businesses_and_never_employees(billing: list[Any]) -> None:
    client = Client()
    ana = account(client, "Ana Solís", "ana@example.com")
    gym = new_business(client, ana, "Ironworks Gym")
    new_business(client, ana, "Ana's Spa")
    owner_token = enter(client, ana, gym["slug"])["token"]
    org = next(n for n in verify(owner_token).nodes if n.kind == "org")
    join(client, owner_token, "lee@example.com", "admin", org.id)  # an employee: never listed
    account(client, "Inv", "inv@example.com")  # invited, not joined yet: not counted
    post(client, "/tenant/members", {"email": "inv@example.com", "role": "admin", "scopeId": org.id}, owner_token)
    bo = account(client, "Bo Park", "bo@example.com")
    new_business(client, bo, "Park Dental")
    account(client, "Nobody", "nobody@example.com")  # owns nothing
    staff = admin_token(client)

    listed = get(client, "/admin/owners", staff).json()
    assert (listed["total"], listed["limit"], listed["billingAvailable"]) == (2, 50, True)
    by_email = {o["email"]: o for o in listed["owners"]}
    assert set(by_email) == {"ana@example.com", "bo@example.com"}
    ana_row = by_email["ana@example.com"]
    assert [b["name"] for b in ana_row["businesses"]] == ["Ana's Spa", "Ironworks Gym"]
    gym_row = next(b for b in ana_row["businesses"] if b["slug"] == gym["slug"])
    assert gym_row["members"] == 2
    assert gym_row["billing"]["plan"] == "Starter"
    assert ana_row["status"] == "active"
    summaries = [s for s in billing if s[1] == "/internal/admin/summaries"]
    assert len(summaries) == 1
    assert len(summaries[0][2]["tenantIds"]) == 3

    def search(q: str) -> list[str]:
        return [o["email"] for o in get(client, f"/admin/owners?q={q}", staff).json()["owners"]]

    assert search("park") == ["bo@example.com"]
    assert search("ANA@") == ["ana@example.com"]
    assert search("spa") == ["ana@example.com"]
    assert search("lee") == []


def test_only_an_admin_creates_an_owner_with_their_first_business_and_its_plan(billing: list[Any]) -> None:
    client = Client()
    staff = admin_token(client)
    body = {
        "name": "Ana Solís",
        "email": "Ana@Example.com",
        "password": "correct-horse",
        "business": {"name": "Ironworks Gym", "industry": "Gym", "locationName": "Union Square"},
        "plan": "growth",
        "reason": "signed the order form",
    }
    created = post(client, "/admin/owners", body, staff)
    assert created.status_code == 200, created.content
    owner = created.json()
    assert (owner["email"], owner["business"]["name"], owner["business"]["billingPending"]) == (
        "ana@example.com",
        "Ironworks Gym",
        False,
    )
    tenant_id = owner["business"]["id"]
    forwarded = next(b for m, p, b in billing if p == f"/internal/tenants/{tenant_id}/plan")
    assert (forwarded["plan"], forwarded["reason"], forwarded["actor"]["name"]) == (
        "growth",
        "signed the order form",
        "Dana Staff (Tenantly)",
    )
    assert Tenant.objects.get(id=tenant_id).plan == "Growth"  # what billing imports if it missed the call
    logged = AdminAuditEvent.objects.filter(action="owner.created").get()
    assert logged.after["business"] == "Ironworks Gym"

    # The owner signs in to their business; the same email is never created twice.
    session = post(client, "/auth/login", {"email": "ana@example.com", "password": "correct-horse"}).json()["token"]
    assert [w["role"] for w in get(client, "/me/workspaces", session).json()] == ["owner"]
    assert post(client, "/admin/owners", body, staff).status_code == 409
    short = post(client, "/admin/owners", {**body, "email": "bo@example.com", "password": "short"}, staff)
    assert short.status_code == 422
    assert not User.objects.filter(email="bo@example.com").exists()

    # A second business, on its own subscription.
    more = {"business": {"name": "Ana's Spa", "locationName": "Main"}, "plan": "starter", "reason": "expansion"}
    spa = post(client, f"/admin/owners/{owner['id']}/businesses", more, staff)
    assert spa.status_code == 200, spa.content
    assert sorted(w["tenant"]["name"] for w in get(client, "/me/workspaces", session).json()) == [
        "Ana's Spa",
        "Ironworks Gym",
    ]
    # A tenant session can't reach any of it.
    assert post(client, "/admin/owners", body, session).status_code == 401


def test_owner_created_team_accounts_ride_on_the_owners_business(billing: list[Any]) -> None:
    client = Client()
    ana = account(client, "Ana", "ana@example.com")
    gym = new_business(client, ana)
    owner_token = enter(client, ana, gym["slug"])["token"]
    org = next(n for n in verify(owner_token).nodes if n.kind == "org")
    lee = join(client, owner_token, "lee@example.com", "admin", org.id)
    assert User.objects.get(email="lee@example.com").created_by.email == "ana@example.com"
    # In the business at once, under its plan; not an owner, so never in the console.
    assert [w["tenant"]["slug"] for w in get(client, "/me/workspaces", lee).json()] == [gym["slug"]]
    staff = admin_token(client)
    assert [o["email"] for o in get(client, "/admin/owners", staff).json()["owners"]] == ["ana@example.com"]

    # Only the owner creates accounts; others may only invite people who have one.
    admin_tenant = enter(client, lee, gym["slug"])["token"]
    body = {
        "email": "kim@example.com",
        "role": "analyst",
        "scopeId": org.id,
        "name": "Kim",
        "password": "correct-horse",
    }
    refused = post(client, "/tenant/members", body, admin_tenant)
    assert refused.status_code == 403
    assert not User.objects.filter(email="kim@example.com").exists()
    assert get(client, "/tenant/members", admin_tenant).json()["canCreateAccounts"] is False
    missing = post(client, "/tenant/members", {**body, "password": ""}, owner_token)
    assert missing.status_code == 422


def test_open_business_is_the_consoles_new_owner_for_scripts() -> None:
    out = io.StringIO()
    call_command(
        "open_business", "Ana@Example.com", "Ironworks Gym", "--location", "Union Square",
        "--name", "Ana", "--password", "correct-horse", stdout=out,
    )  # fmt: skip
    first = json.loads(out.getvalue())
    out = io.StringIO()
    call_command("open_business", "ana@example.com", "Ana's Spa", "--location", "Main", stdout=out)
    assert json.loads(out.getvalue())["slug"] != first["slug"]
    client = Client()
    session = post(client, "/auth/login", {"email": "ana@example.com", "password": "correct-horse"}).json()["token"]
    assert sorted(w["tenant"]["name"] for w in get(client, "/me/workspaces", session).json()) == [
        "Ana's Spa",
        "Ironworks Gym",
    ]
    with pytest.raises(CommandError, match="no account yet"):
        call_command("open_business", "bo@example.com", "Park Dental", "--location", "Main", stdout=io.StringIO())
    assert AdminAuditEvent.objects.filter(action="business.created").count() == 2


def test_billing_down_still_lists_owners_without_billing() -> None:
    client = Client()
    ana = account(client, "Ana", "ana@example.com")
    new_business(client, ana)
    staff = admin_token(client)

    def down(request: httpx.Request) -> httpx.Response:
        msg = "connection refused"
        raise httpx.ConnectError(msg, request=request)

    use_transport(httpx.MockTransport(down))
    try:
        listed = get(client, "/admin/owners", staff).json()
    finally:
        use_transport(None)
    assert listed["billingAvailable"] is False
    assert [b["billing"] for b in listed["owners"][0]["businesses"]] == [None]


def test_suspending_and_restricting_an_owner_are_logged_before_and_after(billing: list[Any]) -> None:
    client = Client()
    ana = account(client, "Ana", "ana@example.com")
    gym = new_business(client, ana)
    staff = admin_token(client)
    ana_id = get(client, "/me", ana).json()["id"]
    path = f"/admin/owners/{ana_id}/status"

    done = put(client, path, {"status": "suspended", "reason": "chargeback fraud"}, staff)
    assert done.status_code == 200, done.content
    assert done.json()["status"] == "suspended"
    assert not Session.objects.filter(user_id=ana_id).exists()
    assert get(client, "/me", ana).status_code == 401
    refused = post(client, "/auth/login", {"email": "ana@example.com", "password": "correct-horse"})
    assert (refused.status_code, "suspended" in refused.json()["detail"]) == (401, True)
    wrong = post(client, "/auth/login", {"email": "ana@example.com", "password": "nope-nope"})
    assert "suspended" not in wrong.json()["detail"]
    entry = AuditEvent.objects.filter(tenant_id=gym["id"]).order_by("-seq").first()
    assert (entry.action, entry.category, entry.actor_name) == ("owner.suspended", "security", "Dana Staff (Tenantly)")
    logged = AdminAuditEvent.objects.filter(kind="action").first()
    assert (logged.action, logged.target_type, logged.target_id) == ("owner.status", "user", ana_id)
    assert (logged.before, logged.after) == (
        {"status": "active"},
        {"status": "suspended", "reason": "chargeback fraud"},
    )

    # Restricted: signs in, reads, changes nothing.
    put(client, path, {"status": "restricted", "reason": "unpaid dispute"}, staff)
    session = post(client, "/auth/login", {"email": "ana@example.com", "password": "correct-horse"}).json()["token"]
    entered = enter(client, session, gym["slug"])
    assert entered["context"]["restricted"] is True
    tenant_token = entered["token"]
    assert verify(tenant_token).access == "restricted"
    assert get(client, "/tenant/members", tenant_token).status_code == 200
    org = next(n for n in verify(tenant_token).nodes if n.kind == "org")
    blocked = post(
        client, "/tenant/members", {"email": "x@example.com", "role": "admin", "scopeId": org.id}, tenant_token
    )
    assert (blocked.status_code, blocked.json()["code"]) == (403, "forbidden")
    assert "restricted" in blocked.json()["detail"]

    put(client, path, {"status": "active", "reason": "resolved"}, staff)
    back = enter(client, session, gym["slug"])["token"]
    assert verify(back).access == "active"
    body = {"email": "x@example.com", "role": "admin", "scopeId": org.id, "name": "Xi", "password": "correct-horse"}
    invited = post(client, "/tenant/members", body, back)
    assert invited.status_code == 200, invited.content
    assert [e.after["status"] for e in AdminAuditEvent.objects.filter(action="owner.status").order_by("id")] == [
        "suspended",
        "restricted",
        "active",
    ]
    assert put(client, path, {"status": "suspended", "reason": ""}, staff).status_code == 422
    assert put(client, "/admin/owners/not-a-uuid/status", {"status": "active", "reason": "x"}, staff).status_code == 404


# ------------------------------------------------------- billing, forwarded --


def test_billing_changes_are_forwarded_signed_by_the_admin_and_logged(billing: list[Any]) -> None:
    client = Client()
    ana = account(client, "Ana", "ana@example.com")
    gym = new_business(client, ana)
    staff = admin_token(client)
    admin = PlatformAdmin.objects.get(email="staff@tenantly.dev")
    actor = {"id": f"admin:{admin.id}", "name": "Dana Staff (Tenantly)"}
    base = f"/admin/businesses/{gym['id']}"

    missing = get(client, f"{base}/subscription", staff)
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")

    plan = {"plan": "custom", "terms": {"price": "250", "customerLimit": 1000}, "reason": "3-year deal"}
    assert put(client, f"{base}/plan", plan, staff).status_code == 200
    assert billing[-1] == (
        "PUT",
        f"/internal/tenants/{gym['id']}/plan",
        {"plan": "custom", "terms": {"price": "250", "customerLimit": 1000}, "reason": "3-year deal", "actor": actor},
    )
    assert put(client, f"{base}/plan", {"plan": "growth", "reason": ""}, staff).status_code == 422

    grant = {"kind": "extra_allowance", "metric": "active_customers", "value": "50", "days": 31, "reason": "launch"}
    assert post(client, f"{base}/grants", grant, staff).status_code == 200
    assert billing[-1][1:] == (f"/internal/tenants/{gym['id']}/grants", {**grant, "actor": actor})

    invoice = "8a0e2a52-3a43-4f6f-9b7e-0f6f3b8d2a11"
    paid = post(client, f"/admin/invoices/{invoice}/paid", {"reference": "wire #1"}, staff)
    assert paid.status_code == 200
    assert "before" not in paid.json()
    assert billing[-1][1:] == (f"/internal/plan-invoices/{invoice}/paid", {"reference": "wire #1", "actor": actor})

    reprice = {"price": "35.00", "included": 100, "overagePrice": "0.45", "cap": "59.00", "reason": "2027 prices"}
    assert post(client, "/admin/plans/8a0e2a52-3a43-4f6f-9b7e-0f6f3b8d2a12/reprice", reprice, staff).status_code == 200
    assert billing[-1][2]["actor"] == actor
    policy = {
        "limitAfterDays": 10, "restrictAfterDays": 30, "cancelAfterDays": 45, "paymentTermsDays": 14,
        "smallBalance": "5.00", "extensionDays": 7, "extensionEveryDays": 365, "retentionDays": 90,
        "usageGraceHours": 72, "spendCapMultiple": "2.00", "alertThresholds": [80, 100], "reason": "review",
    }  # fmt: skip
    assert put(client, "/admin/policy", policy, staff).status_code == 200

    logged = {e.action: e for e in AdminAuditEvent.objects.filter(kind="action")}
    assert logged["subscription.plan"].before == {"plan": "Starter", "version": 2, "status": "active"}
    assert logged["subscription.plan"].after["plan"] == "Custom"
    assert logged["subscription.grant"].before is None
    assert (logged["invoice.paid"].before, logged["invoice.paid"].after["status"]) == ({"status": "open"}, "paid")
    assert (logged["plan.repriced"].before, logged["plan.repriced"].after["scheduled"]) == ({"price": "29.00"}, 4)
    assert (logged["policy.edited"].before, logged["policy.edited"].after) == ({"version": 1}, {"version": 2})
    assert all(e.admin_id == admin.id for e in logged.values())

    # The log, newest first, is readable from the console and nowhere else.
    log = get(client, "/admin/audit", staff).json()
    assert log["events"][0]["action"] == "policy.edited"
    assert log["events"][0]["admin"]["email"] == "staff@tenantly.dev"
    assert log["total"] == AdminAuditEvent.objects.count()

    assert get(client, "/admin/businesses/8a0e2a52-3a43-4f6f-9b7e-0f6f3b8d2a11/subscription", staff).status_code == 404
    assert post(client, "/admin/invoices/nope/paid", {"reference": "x"}, staff).status_code == 404
