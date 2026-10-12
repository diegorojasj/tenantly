"""What Tenantly admins change through billing: the versioned billing policy (validated, and
actually what standing and invoices follow) and plan price lists (a new version; businesses
move at renewal, are told, and issued invoices never change)."""

# Fixtures like `clock` and `identity` are requested for their effect, and imported from test_plans.
# ruff: noqa: ARG001, F811

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from src.models import BillingNotice, BillingPolicy, PlanInvoice, PlanVersion, SubscriptionChange, TenantSubscription
from src.services import catalog, cycle, policy, standing

from .test_console import ADMIN, internal
from .test_plans import Clock, clock, close_november, customers, held, identity, plan, serve  # noqa: F401

pytestmark = pytest.mark.django_db

FIRST = {
    "limitAfterDays": 14,
    "restrictAfterDays": 30,
    "cancelAfterDays": 45,
    "paymentTermsDays": 14,
    "smallBalance": "5.00",
    "extensionDays": 7,
    "extensionEveryDays": 365,
    "retentionDays": 90,
    "usageGraceHours": 72,
    "spendCapMultiple": "2.00",
    "alertThresholds": [80, 100],
}


def edit(client: Client, **changes: Any) -> Any:
    body = {**FIRST, "reason": "Collections review", "actor": ADMIN, **changes}
    return internal(client, "put", "/internal/admin/policy", body)


def test_the_policy_starts_with_the_old_constants_and_every_edit_is_a_validated_new_version(clock: Clock) -> None:
    client = Client()
    first = internal(client, "get", "/internal/admin/policy").json()["current"]
    assert {k: first[k] for k in FIRST} == FIRST
    assert first["version"] == 1
    assert client.get("/internal/admin/policy").status_code == 401  # internal only

    for bad in (
        {"limitAfterDays": 30, "restrictAfterDays": 30},  # must run forward
        {"restrictAfterDays": 50},  # past the cancellation day
        {"cancelAfterDays": 400},
        {"paymentTermsDays": 91},
        {"smallBalance": "-1.00"},
        {"spendCapMultiple": "0.50"},
        {"alertThresholds": [0, 100]},
        {"alertThresholds": []},
    ):
        refused = edit(client, **bad)
        assert refused.status_code == 422, bad
    assert edit(client).status_code == 422  # nothing changed
    assert BillingPolicy.objects.count() == 1

    done = edit(client, limitAfterDays=10, alertThresholds=[100, 50, 50])
    assert done.status_code == 200, done.content
    assert (done.json()["before"]["version"], done.json()["after"]["version"]) == (1, 2)
    assert done.json()["after"]["alertThresholds"] == [50, 100]
    assert done.json()["after"]["editedBy"] == "Dana (Tenantly)"
    listing = internal(client, "get", "/internal/admin/policy").json()
    assert [p["version"] for p in listing["history"]] == [2, 1]
    assert listing["current"]["limitAfterDays"] == 10

    # Versions are never edited in place.
    old = BillingPolicy.objects.get(version=1)
    old.limit_after_days = 3
    with pytest.raises(ValueError, match="never edited in place"):
        old.save()


def test_standing_invoices_and_new_subscriptions_follow_the_policy_in_force(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    edit(
        client,
        limitAfterDays=5,
        restrictAfterDays=10,
        cancelAfterDays=20,
        paymentTermsDays=7,
        smallBalance="50.00",
        alertThresholds=[50, 90],
    )
    rules = policy.current()
    assert (rules.version, rules.limit_after_days) == (2, 5)

    invoice = close_november(client, ids, clock)  # $29, issued 4 December
    assert invoice.due_on == date(2026, 12, 11)  # 7-day terms, not 14
    sub = TenantSubscription.objects.get(tenant_id=ids["tenant"])
    assert sub.alert_thresholds == [50, 90]
    # $29 is under the $50 small balance: it never escalates.
    assert standing.of(sub, date(2027, 1, 30)).status == "past_due"

    edit(
        client,
        limitAfterDays=5,
        restrictAfterDays=10,
        cancelAfterDays=20,
        paymentTermsDays=7,
        smallBalance="5.00",
        alertThresholds=[50, 90],
    )
    assert standing.of(sub, date(2026, 12, 16)).status == "limited"  # day 5, not 14
    assert standing.of(sub, date(2026, 12, 21)).status == "restricted"  # day 10, not 30
    page = plan(client, ids)
    assert page["standing"]["limitsOn"] == "2026-12-16"
    assert page["standing"]["cancelsOn"] == "2026-12-31"

    # The cycle cancels on the policy's day and keeps the data for its retention.
    clock.at = datetime(2026, 12, 31, 9, tzinfo=UTC)
    cycle.chase(clock.at.date())
    sub.refresh_from_db()
    assert (sub.status, sub.retention_until) == ("canceled", date(2027, 3, 31))
    warned = set(BillingNotice.objects.filter(tenant_id=ids["tenant"]).values_list("kind", flat=True))
    assert "canceled" in warned


def test_repricing_a_plan_publishes_a_version_and_moves_its_businesses_at_renewal(
    ids: dict[str, str], clock: Clock, identity: list[Any]
) -> None:
    client = Client()
    for c in customers(80):
        serve(client, ids, c)
    starter = catalog.public("starter")
    listing = internal(client, "get", "/internal/admin/plans").json()
    row = next(p for p in listing["plans"] if p["id"] == str(starter.id))
    assert (row["subscribers"], row["usage"]) == (1, {"used": 80, "over": 1})

    path = f"/internal/admin/plans/{starter.id}/reprice"
    body = {"price": "35.00", "included": 100, "overagePrice": "0.45", "cap": "59.00", "reason": "2027 prices"}
    assert internal(client, "post", path, {**body, "reason": ""}).status_code == 422
    assert internal(client, "post", path, {**body, "cap": "20.00"}).status_code == 422  # cap under price
    same = {"price": "29.00", "included": 75, "overagePrice": "0.40", "cap": "59.00", "reason": "x"}
    assert internal(client, "post", path, same).status_code == 422

    done = internal(client, "post", path, {**body, "actor": ADMIN})
    assert done.status_code == 200, done.content
    out = done.json()
    assert (out["before"]["price"], out["after"]["price"], out["scheduled"]) == ("29.00", "35.00", 1)
    new = PlanVersion.objects.get(id=out["after"]["id"])
    starter.refresh_from_db()
    assert (starter.status, new.status, new.version) == ("legacy", "active", starter.version + 1)
    assert catalog.public("starter").id == new.id  # what new businesses are offered
    assert internal(client, "post", path, body).status_code == 422  # the old list is no longer on sale

    sub = TenantSubscription.objects.get(tenant_id=ids["tenant"])
    assert (sub.plan_version_id, sub.scheduled_plan_version_id) == (starter.id, new.id)
    change = SubscriptionChange.objects.filter(subscription=sub).first()
    assert (change.kind, change.actor_name, change.detail) == (
        "reprice_scheduled",
        "Dana (Tenantly)",
        {"reason": "2027 prices"},
    )
    notice = BillingNotice.objects.get(tenant_id=ids["tenant"], kind="plan_repriced")
    assert notice.params["oldPrice"] == "29.00"
    assert notice.params["price"] == "35.00"
    assert notice.params["effectiveOn"] == "2026-12-01"

    # November is still billed on the old price; the issued invoice never changes after.
    invoice = close_november(client, ids, clock)
    assert invoice.total == Decimal("31.00")  # $29 + 5 x $0.40
    sub.refresh_from_db()
    assert (sub.plan_version_id, sub.scheduled_plan_version_id) == (new.id, None)
    assert SubscriptionChange.objects.filter(subscription=sub).first().kind == "reprice_applied"
    assert plan(client, ids)["plan"]["price"] == "35.00"
    assert PlanInvoice.objects.get(id=invoice.id).total == Decimal("31.00")

    # Only public versions on sale can be repriced.
    assert internal(client, "post", "/internal/admin/plans/nope/reprice", body).status_code == 404
    assert client.post(path, body, content_type="application/json").status_code == 401  # internal only
