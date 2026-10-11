from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from common.auth import Node, TenantClaims, issue
from common.internal import use_transport


@dataclass
class Calls:
    """Every internal call operations made (to identity and billing), in order."""

    log: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # Hosts that answer 502, to simulate a service being down.
    down: set[str] = field(default_factory=set)
    # What billing answers for balances (customer id -> {"spend", "balance"} decimal strings).
    balances: dict[str, dict[str, str]] = field(default_factory=dict)

    def paths(self) -> list[str]:
        return [p for p, _ in self.log]

    def bodies(self, path_part: str) -> list[dict[str, Any]]:
        return [b for p, b in self.log if path_part in p]


@pytest.fixture
def calls() -> Calls:
    record = Calls()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in record.down:
            return httpx.Response(502, text="<html>Bad gateway</html>")
        body = json.loads(request.content) if request.content else {}
        record.log.append((request.url.path, body))
        path = request.url.path
        if path.endswith("/internal/balances"):
            return httpx.Response(200, json=record.balances)
        if path.endswith("/internal/revenue"):
            return httpx.Response(200, json={"byDay": {}, "byLocation": {}})
        if "/charges" in path and request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"ok": True})

    use_transport(httpx.MockTransport(handler))
    yield record
    use_transport(None)


STAFF = {"type": "staff", "quantity": 1, "pick": True}
# The presets identity's migration 0006 turned the old kinds into.
PRESETS: dict[str, dict[str, Any]] = {
    "appointment": {"key": "appointment", "label": "Appointment", "plural": "Appointments", "capacity": 1,
                    "time": "slot", "units": ["session"], "place": "on_site", "requires": [STAFF]},
    "class": {"key": "class", "label": "Class", "plural": "Classes", "capacity": 12,
              "time": "slot", "units": ["session"], "place": "on_site", "requires": [STAFF]},
    "rental": {"key": "rental", "label": "Rental", "plural": "Rentals", "capacity": 1, "time": "window",
               "units": ["hour", "day", "night", "month"], "place": "on_site",
               "requires": [{"type": "asset", "quantity": 1, "pick": False, "named": True}]},
    "visit": {"key": "visit", "label": "Visit", "plural": "Visits", "capacity": 1,
              "time": "slot", "units": ["session"], "place": "at_customer", "requires": [STAFF]},
    "plan": {"key": "plan", "label": "Plan", "plural": "Plans", "capacity": None,
             "time": "none", "units": ["month", "pack"], "place": "on_site", "requires": []},
}  # fmt: skip

# The fitness template's rules as identity puts them in the token (Template.rules(), after identity 0007).
FITNESS: dict[str, Any] = {
    "version": 2,
    "label": "Fitness",
    "presets": [PRESETS["class"], PRESETS["appointment"], PRESETS["plan"]],
    "resourceTypes": [
        {"key": "staff", "label": "Coach", "plural": "Coaches", "people": True, "roleLabel": "Specialty",
         "attributes": []},
        {"key": "asset", "label": "Room", "plural": "Rooms", "people": False, "roleLabel": "Type",
         "attributes": [{"key": "capacity", "label": "Capacity", "type": "number"}]},
    ],
    "terms": {
        "customer": "Member", "customers": "Members", "booking": "Booking", "bookings": "Bookings",
        "staff": "Coach", "staffPlural": "Coaches", "asset": "Room", "assets": "Rooms",
        "location": "Club", "locations": "Clubs",
    },
    "status": {
        "requested": "Waitlisted", "confirmed": "Booked", "checked_in": "Checked in",
        "completed": "Attended", "no_show": "No-show", "cancelled": "Cancelled",
    },
    "transitions": {
        "requested": ["confirmed", "cancelled"],
        "confirmed": ["checked_in", "no_show", "cancelled"],
        "checked_in": ["completed"],
        "completed": [], "no_show": [], "cancelled": [],
    },
    "fields": {
        "customer": [
            {"key": "goal", "label": "Goal", "type": "text"},
            {"key": "injuries", "label": "Injuries", "type": "text", "pii": True},
            {"key": "emergency", "label": "Emergency contact", "type": "text", "pii": True},
        ],
    },
    "accountTypes": [{"key": "household", "label": "Family", "plural": "Families", "fields": []}],
    "subjectTypes": [],
    "documents": [{"key": "waiver", "label": "Waiver", "appliesTo": "customer", "validDays": None}],
    "open": 6 * 60,
    "close": 21 * 60,
    "policyDefaults": {"docs.require.waiver": "Remind"},
}  # fmt: skip


@dataclass
class Tenant:
    id: str
    org: str
    area: str
    site_a: str
    site_b: str

    def token(
        self,
        role: str = "owner",
        perms: tuple[str, ...] | None = None,
        home: str | None = None,
        template: dict[str, Any] | None = None,
        site_a_clock: tuple[str, tuple[int, int] | None] = ("UTC", None),
        money: dict[str, Any] | None = None,
    ) -> str:
        everything = (
            "bookings.manage", "payments.collect", "tenant.manage", "members.invite", "roles.assign",
            "config.write", "pricing.write", "billing.view", "billing.manage", "audit.view",
            "analytics.view",
        )  # fmt: skip
        claims = TenantClaims(
            user_id=str(uuid.uuid4()),
            user_name="Ana",
            tenant_id=self.id,
            tenant_slug="ironworks",
            template_id="custom" if template else "fitness",
            role=role,
            permissions=perms or everything,
            home_scope_id=home or self.org,
            nodes=(
                Node(self.org, None, "org", "Ironworks"),
                Node(self.area, self.org, "region", "Manhattan"),
                Node(self.site_a, self.area, "location", "Union Square", *site_a_clock),
                Node(self.site_b, self.org, "location", "Brooklyn"),
            ),
            template=template or FITNESS,
            money=money or {},
        )
        return issue(claims)


@pytest.fixture
def tenant() -> Tenant:
    return Tenant(*(str(uuid.uuid4()) for _ in range(5)))
