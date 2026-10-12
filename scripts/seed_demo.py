#!/usr/bin/env python3
"""Seed Tenantly with demo businesses, through the same APIs the app uses.

Eight very different businesses, all on the one generic template, to show the same
product running a gym, rentals & tours, home services, a salon, a vet, coworking, a
music school and car detailing. Each gets locations (some grouped into areas), a team
with roles, a catalog, resources, customers (with companies and households), plans,
documents, policies, the next week of bookings and classes, and then months of history.

The API only books from now on, so history is written by the operations service's
`seed_history` command, run inside its container at the end. The Tenantly plan is set
by Tenantly, not the owner, so it goes through identity's `set_plan` command (billing
applies it); between them the businesses show every plan: Starter, Growth, Enterprise
and a Custom one. A business's billing period starts when it's created, so the
back-dated history isn't usage: the plan's meter fills as bookings are served from now on
(docs/BILLING.md).

    podman compose --profile DEV up -d --build     # the stack, with seed_history baked in
    python3 scripts/seed_demo.py                   # http://localhost:8080 by default

Sign in as demo@tenantly.dev / demo-pass-2026 (owner of all four). Every team member
uses the same password. Running it again skips businesses that already exist (their
plan is still set); `--reset` deletes the demo businesses first and seeds them anew.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PASSWORD = "demo-pass-2026"  # noqa: S105 - a published demo password
OWNER = ("Alex Rivera", "demo@tenantly.dev")

FIRST = (
    "Ana Ben Carla David Elena Farid Grace Hugo Iris Jamal Kenji Lucia Marco Nadia Omar Priya Quinn Rosa Sam Tara "
    "Umar Vera Will Xenia Yusuf Zoe Leo Mia Noah Ava Liam Emma Ethan Sofia Mateo Chloe Lucas Isla Diego Nora Kai "
    "Maya Ravi Lena Theo Aisha Felix Hana Ivan Julia"
).split()
LAST = (
    "Garcia Smith Chen Okafor Rossi Novak Silva Kim Patel Müller Dubois Haddad Nguyen Jensen Costa Ivanova Tanaka "
    "Moreno Walsh Laurent Brooks Singh Ortiz Fischer Bianchi Ahmed Kowalski Reyes Lindqvist Duarte"
).split()

# Each business: who it is, where it works, who works there and what it sells.
# Offerings: (kind, name, category, price, extra fields); resources: (type, role, names).
# Where each demo location sits: street address and map pin. "Mobile Fleet" has no
# storefront, so it stays off the map (the Locations page lists it as "not placed").
PLACES: dict[str, tuple[str, float, float]] = {
    "Chelsea": ("150 W 22nd St, New York, NY 10011", 40.7428, -73.9945),
    "Upper West Side": ("2121 Broadway, New York, NY 10023", 40.7799, -73.9817),
    "Williamsburg": ("94 N 6th St, Brooklyn, NY 11249", 40.7197, -73.9603),
    "Pier 39 Dock": ("Pier 39, The Embarcadero, San Francisco, CA 94133", 37.8087, -122.4098),
    "Sausalito Marina": ("300 Harbor Dr, Sausalito, CA 94965", 37.8636, -122.4955),
    "North Route": ("3500 N Lincoln Ave, Chicago, IL 60657", 41.9465, -87.6740),
    "South Route": ("1500 S Michigan Ave, Chicago, IL 60605", 41.8622, -87.6243),
    "Evanston": ("1630 Sherman Ave, Evanston, IL 60201", 42.0464, -87.6812),
    "Malasaña": ("Calle del Espíritu Santo 18, 28004 Madrid", 40.4250, -3.7047),
    "Downtown Clinic": ("1600 Wynkoop St, Denver, CO 80202", 39.7528, -105.0002),
    "Foothills Clinic": ("2525 Arapahoe Ave, Boulder, CO 80302", 40.0150, -105.2593),
    "FiDi Hub": ("40 Wall St, New York, NY 10005", 40.7069, -74.0089),
    "Midtown Hub": ("500 Fifth Ave, New York, NY 10110", 40.7537, -73.9810),
    "Silver Lake Studio": ("3812 Sunset Blvd, Los Angeles, CA 90026", 34.0912, -118.2780),
    "Downtown Bay": ("600 S Wells St, Chicago, IL 60607", 41.8743, -87.6338),
}

BUSINESSES: list[dict[str, Any]] = [
    {
        "name": "Pulse Fitness Studio",
        # Past Enterprise in payments (classes every day): a plan negotiated with Tenantly.
        "plan": ("Custom", {"price": "149", "customers": 300}),
        "industry": "Fitness studio",
        "currency": "USD",
        "tz": "America/New_York",
        "hours": (6 * 60, 22 * 60),
        "locations": [("Chelsea", None), ("Upper West Side", "Manhattan"), ("Williamsburg", "Brooklyn")],
        "customers": 140,
        "plan_share": 0.45,
        "per_day": 9,
        "policies": {"payments.noShowFee": "50% of price", "booking.cancelHours": 6},
        "offerings": [
            ("class", "Spin 45", "Classes", "25", {"minutes": 45, "capacity": 16, "requires": [
                {"type": "staff", "quantity": 1, "role": "Instructor"}, {"type": "asset", "quantity": 1, "role": "Studio"}]}),
            ("class", "Vinyasa Yoga", "Classes", "22", {"minutes": 60, "capacity": 20, "requires": [
                {"type": "staff", "quantity": 1, "role": "Instructor"}, {"type": "asset", "quantity": 1, "role": "Studio"}]}),
            ("class", "HIIT Express", "Classes", "18", {"minutes": 30, "capacity": 12, "requires": [
                {"type": "staff", "quantity": 1, "role": "Instructor"}]}),
            ("appointment", "Personal training", "Coaching", "85", {"minutes": 60, "requires": [
                {"type": "staff", "quantity": 1, "role": "Trainer"}]}),
            ("appointment", "Sports massage", "Recovery", "95", {"minutes": 50, "requires": [
                {"type": "staff", "quantity": 1, "role": "Therapist"}]}),
            ("plan", "Unlimited monthly", "Memberships", "149", {"unit": "month"}),
            ("plan", "10-class pack", "Memberships", "199", {"unit": "pack", "credits": 10}),
        ],
        "resources": [
            ("staff", "Instructor", 3), ("staff", "Trainer", 2), ("staff", "Therapist", 1),
            ("asset", "Studio", ["Studio A", "Studio B"]),
        ],
        "team": [("admin", "Jordan Lee"), ("location_manager", "Priya Shah"), ("analyst", "Tom Becker")],
    },
    {
        "name": "Harbor Rentals & Tours",
        "plan": ("Enterprise", {}),
        "industry": "Kayak, bike and paddleboard hire, guided tours",
        "currency": "USD",
        "tz": "America/Los_Angeles",
        "hours": (8 * 60, 19 * 60),
        "locations": [("Pier 39 Dock", None), ("Sausalito Marina", None)],
        "customers": 110,
        "plan_share": 0.08,
        "per_day": 12,
        "waivers": True,
        "policies": {"docs.require.waiver": "Remind", "payments.deposit": 20},
        "approval_at": "Sausalito Marina",
        "offerings": [
            ("rental", "Single kayak", "Kayaks", "25", {"unit": "hour", "minutes": 120, "requires": [
                {"type": "asset", "quantity": 1, "role": "Kayak"}]}),
            ("rental", "Stand-up paddleboard", "Boards", "20", {"unit": "hour", "minutes": 60, "requires": [
                {"type": "asset", "quantity": 1, "role": "Paddleboard"}]}),
            ("rental", "E-bike day hire", "Bikes", "65", {"unit": "day", "requires": [
                {"type": "asset", "quantity": 1, "role": "E-bike"}]}),
            ("class", "Sunset kayak tour", "Tours", "75", {"minutes": 120, "capacity": 10, "requires": [
                {"type": "staff", "quantity": 1, "role": "Guide"}]}),
            ("class", "Golden Gate bike tour", "Tours", "55", {"minutes": 180, "capacity": 12, "requires": [
                {"type": "staff", "quantity": 1, "role": "Guide"}]}),
            ("plan", "Season pass", "Passes", "89", {"unit": "month"}),
        ],
        "resources": [
            ("staff", "Guide", 3),
            ("asset", "Kayak", [f"Kayak {n:02d}" for n in range(1, 9)]),
            ("asset", "Paddleboard", [f"Board {n}" for n in range(1, 5)]),
            ("asset", "E-bike", [f"E-bike {n}" for n in range(1, 7)]),
        ],
        "team": [("location_manager", "Marisol Vega"), ("location_manager", "Ethan Cole")],
    },
    {
        "name": "BrightHome Services",
        "plan": ("Growth", {}),
        "industry": "Home cleaning, HVAC and plumbing",
        "currency": "USD",
        "tz": "America/Chicago",
        "hours": (7 * 60, 19 * 60),
        "locations": [("North Route", "Chicago"), ("South Route", "Chicago"), ("Evanston", "Suburbs")],
        "customers": 90,
        "plan_share": 0.3,
        "per_day": 7,
        "accounts": True,
        "policies": {"booking.cancelHours": 24, "payments.noShowFee": "25% of price"},
        "offerings": [
            ("visit", "Standard home clean", "Cleaning", "140", {"minutes": 120, "requires": [
                {"type": "staff", "quantity": 1, "role": "Cleaner"}]}),
            ("visit", "Deep clean", "Cleaning", "260", {"minutes": 240, "requires": [
                {"type": "staff", "quantity": 2, "role": "Cleaner"}]}),
            ("visit", "AC tune-up", "HVAC", "120", {"minutes": 90, "requires": [
                {"type": "staff", "quantity": 1, "role": "Technician"},
                {"type": "asset", "quantity": 1, "role": "Van"}]}),
            ("visit", "Plumbing call-out", "Plumbing", "95", {"minutes": 60, "requires": [
                {"type": "staff", "quantity": 1, "role": "Plumber"},
                {"type": "asset", "quantity": 1, "role": "Van"}]}),
            ("plan", "Home care plan", "Plans", "49", {"unit": "month"}),
        ],
        "resources": [
            ("staff", "Cleaner", 4), ("staff", "Technician", 2), ("staff", "Plumber", 1),
            ("asset", "Van", ["Van 1", "Van 2"]),
        ],
        "team": [("admin", "Grace Holloway"), ("regional_manager", "Malik Johnson")],
    },
    {
        "name": "Lumen Hair Studio",
        "plan": ("Starter", {}),
        "industry": "Hair salon",
        "currency": "EUR",
        "tz": "Europe/Madrid",
        "hours": (10 * 60, 20 * 60),
        "locations": [("Malasaña", None)],
        # A small salon: fits Starter (up to 50 customers a month).
        "customers": 48,
        "plan_share": 0.0,
        "per_day": 6,
        "policies": {},
        "offerings": [
            ("appointment", "Cut & finish", "Hair", "38", {"minutes": 45, "requires": [
                {"type": "staff", "quantity": 1, "role": "Stylist"}, {"type": "asset", "quantity": 1, "role": "Chair"}]}),
            ("appointment", "Colour", "Hair", "75", {"minutes": 90, "requires": [
                {"type": "staff", "quantity": 1, "role": "Colourist"}, {"type": "asset", "quantity": 1, "role": "Chair"}]}),
            ("appointment", "Blow-dry", "Hair", "25", {"minutes": 30, "requires": [
                {"type": "staff", "quantity": 1, "role": "Stylist"}, {"type": "asset", "quantity": 1, "role": "Chair"}]}),
        ],
        "resources": [
            ("staff", "Stylist", 3), ("staff", "Colourist", 1),
            ("asset", "Chair", [f"Chair {n}" for n in range(1, 5)]),
        ],
        "team": [("location_manager", "Lucía Prieto")],
    },
    {
        "name": "Summit Veterinary Clinic",
        "plan": ("Enterprise", {}),
        "industry": "Veterinary care for small animals",
        "currency": "USD",
        "tz": "America/Denver",
        "hours": (7 * 60, 19 * 60),
        "locations": [("Downtown Clinic", None), ("Foothills Clinic", "Boulder County")],
        "customers": 160,
        "plan_share": 0.25,
        "per_day": 11,
        "accounts": True,
        "policies": {"booking.cancelHours": 12, "payments.noShowFee": "25% of price"},
        "offerings": [
            ("appointment", "Wellness exam", "Checkups", "65", {"minutes": 30, "requires": [
                {"type": "staff", "quantity": 1, "role": "Veterinarian"}, {"type": "asset", "quantity": 1, "role": "Exam room"}]}),
            ("appointment", "Vaccination", "Preventive", "45", {"minutes": 20, "requires": [
                {"type": "staff", "quantity": 1, "role": "Vet tech"}, {"type": "asset", "quantity": 1, "role": "Exam room"}]}),
            ("appointment", "Dental cleaning", "Dental", "220", {"minutes": 90, "requires": [
                {"type": "staff", "quantity": 1, "role": "Veterinarian"}, {"type": "asset", "quantity": 1, "role": "Surgery suite"}]}),
            ("appointment", "Spay/neuter surgery", "Surgery", "350", {"minutes": 120, "requires": [
                {"type": "staff", "quantity": 1, "role": "Veterinarian"}, {"type": "asset", "quantity": 1, "role": "Surgery suite"}]}),
            ("appointment", "Grooming", "Grooming", "55", {"minutes": 60, "requires": [
                {"type": "staff", "quantity": 1, "role": "Groomer"}]}),
            ("plan", "Pet wellness plan", "Plans", "39", {"unit": "month"}),
        ],
        "resources": [
            ("staff", "Veterinarian", 3), ("staff", "Vet tech", 3), ("staff", "Groomer", 1),
            ("asset", "Exam room", ["Exam 1", "Exam 2", "Exam 3"]), ("asset", "Surgery suite", ["Suite A"]),
        ],
        "team": [("admin", "Dr. Nina Castro"), ("location_manager", "Owen Park"), ("analyst", "Rhea Banerjee")],
    },
    {
        "name": "Juniper Coworking",
        "plan": ("Enterprise", {}),
        "industry": "Coworking space and meeting room rental",
        "currency": "USD",
        "tz": "America/New_York",
        "hours": (7 * 60, 21 * 60),
        "locations": [("FiDi Hub", None), ("Midtown Hub", "Manhattan")],
        "customers": 130,
        "plan_share": 0.55,
        "per_day": 8,
        "accounts": True,
        "policies": {"booking.cancelHours": 2, "payments.deposit": 10},
        "offerings": [
            ("rental", "Hot desk", "Desks", "35", {"unit": "day", "requires": [
                {"type": "asset", "quantity": 1, "role": "Desk"}]}),
            ("rental", "Private office", "Offices", "120", {"unit": "day", "requires": [
                {"type": "asset", "quantity": 1, "role": "Office"}]}),
            ("rental", "Meeting room (4-person)", "Meeting rooms", "25", {"unit": "hour", "minutes": 60, "requires": [
                {"type": "asset", "quantity": 1, "role": "Meeting room"}]}),
            ("rental", "Conference room (12-person)", "Meeting rooms", "60", {"unit": "hour", "minutes": 60, "requires": [
                {"type": "asset", "quantity": 1, "role": "Conference room"}]}),
            ("plan", "Flex monthly", "Memberships", "249", {"unit": "month"}),
            ("plan", "Dedicated desk monthly", "Memberships", "349", {"unit": "month"}),
        ],
        "resources": [
            ("asset", "Desk", [f"Desk {n:02d}" for n in range(1, 21)]),
            ("asset", "Office", [f"Office {n}" for n in range(1, 7)]),
            ("asset", "Meeting room", ["Meeting A", "Meeting B", "Meeting C"]),
            ("asset", "Conference room", ["Conference 1"]),
            ("staff", "Community manager", 2),
        ],
        "team": [("admin", "Casey Whitfield"), ("location_manager", "Imani Osei")],
    },
    {
        "name": "Crescendo Music Academy",
        "plan": ("Growth", {}),
        "industry": "Private music lessons and group classes",
        "currency": "USD",
        "tz": "America/Los_Angeles",
        "hours": (9 * 60, 20 * 60),
        "locations": [("Silver Lake Studio", None)],
        "customers": 95,
        "plan_share": 0.4,
        "per_day": 9,
        "policies": {"booking.cancelHours": 24, "payments.noShowFee": "50% of price"},
        "offerings": [
            ("appointment", "Piano lesson", "Lessons", "60", {"minutes": 45, "requires": [
                {"type": "staff", "quantity": 1, "role": "Piano teacher"}, {"type": "asset", "quantity": 1, "role": "Piano room"}]}),
            ("appointment", "Guitar lesson", "Lessons", "55", {"minutes": 45, "requires": [
                {"type": "staff", "quantity": 1, "role": "Guitar teacher"}, {"type": "asset", "quantity": 1, "role": "Practice room"}]}),
            ("appointment", "Voice coaching", "Lessons", "65", {"minutes": 45, "requires": [
                {"type": "staff", "quantity": 1, "role": "Voice coach"}, {"type": "asset", "quantity": 1, "role": "Practice room"}]}),
            ("class", "Toddler music & movement", "Group classes", "20", {"minutes": 40, "capacity": 10, "requires": [
                {"type": "staff", "quantity": 1, "role": "Group instructor"}]}),
            ("class", "Beginner ukulele group", "Group classes", "18", {"minutes": 45, "capacity": 8, "requires": [
                {"type": "staff", "quantity": 1, "role": "Group instructor"}]}),
            ("plan", "4 lessons/month", "Packages", "220", {"unit": "pack", "credits": 4}),
            ("plan", "8 lessons/month", "Packages", "410", {"unit": "pack", "credits": 8}),
        ],
        "resources": [
            ("staff", "Piano teacher", 2), ("staff", "Guitar teacher", 2),
            ("staff", "Voice coach", 1), ("staff", "Group instructor", 1),
            ("asset", "Piano room", ["Piano room 1", "Piano room 2"]),
            ("asset", "Practice room", ["Practice room A", "Practice room B"]),
        ],
        "team": [("location_manager", "Benedict Ortega"), ("analyst", "Sierra Nakamura")],
    },
    {
        "name": "Northbound Auto Detailing",
        # Chose Starter but serves ~100 customers a month: billing moves it up to Growth.
        "plan": ("Starter", {}),
        "industry": "Mobile car detailing and ceramic coating",
        "currency": "USD",
        "tz": "America/Chicago",
        "hours": (8 * 60, 18 * 60),
        "locations": [("Downtown Bay", None), ("Mobile Fleet", "Metro Area")],
        "customers": 100,
        "plan_share": 0.15,
        "per_day": 6,
        "accounts": True,
        "policies": {"booking.cancelHours": 12, "payments.deposit": 25},
        "offerings": [
            ("visit", "Express wash & vacuum", "Wash", "40", {"minutes": 45, "requires": [
                {"type": "staff", "quantity": 1, "role": "Detailer"}]}),
            ("visit", "Full interior/exterior detail", "Detail", "150", {"minutes": 150, "requires": [
                {"type": "staff", "quantity": 1, "role": "Detailer"}, {"type": "asset", "quantity": 1, "role": "Bay"}]}),
            ("visit", "Ceramic coating", "Protection", "600", {"minutes": 300, "requires": [
                {"type": "staff", "quantity": 2, "role": "Detailer"}, {"type": "asset", "quantity": 1, "role": "Bay"}]}),
            ("visit", "Paint correction", "Protection", "380", {"minutes": 240, "requires": [
                {"type": "staff", "quantity": 1, "role": "Detailer"}, {"type": "asset", "quantity": 1, "role": "Bay"}]}),
            ("plan", "Monthly maintenance wash", "Plans", "69", {"unit": "month"}),
        ],
        "resources": [
            ("staff", "Detailer", 4),
            ("asset", "Bay", ["Bay 1", "Bay 2"]),
            ("asset", "Van", ["Detail Van 1", "Detail Van 2"]),
        ],
        "team": [("admin", "Hector Delgado"), ("location_manager", "Wren Castillo")],
    },
]


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: Any = None, token: str | None = None, ok: tuple[int, ...] = ()) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self.base}{path}", data=data, method=method)  # noqa: S310 - local API
        request.add_header("accept", "application/json")
        if data is not None:
            request.add_header("content-type", "application/json")
        if token:
            request.add_header("authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code in ok:
                return None
            detail = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"{method} {path} → {exc.code}: {detail}") from None


def account(api: Api, email: str, invite: str | None = None) -> str:
    """Sign in (claiming `invite` if given); returns the session token. Nobody signs up: accounts are made for people."""
    extra = {"invite": invite} if invite else {}
    return api.call("POST", "/identity/auth/login", {"email": email, "password": PASSWORD, **extra})["token"]


def slug_email(name: str, business: str) -> str:
    domain = business.lower().split()[0]
    return f"{name.lower().replace(' ', '.').replace('í', 'i').replace('ñ', 'n')}@{domain}.demo"


class Seeder:
    def __init__(self, api: Api, spec: dict[str, Any], session: str, identity_container: str) -> None:
        self.api, self.spec, self.session = api, spec, session
        self.identity_container = identity_container
        self.tz = ZoneInfo(spec["tz"])

    def enter(self) -> None:
        entered = self.api.call("POST", f"/identity/tenants/{self.slug}/token", {"scope": None}, self.session)
        self.token, self.context = entered["token"], entered["context"]

    def ops(self, method: str, path: str, body: Any = None, ok: tuple[int, ...] = ()) -> Any:
        return self.api.call(method, f"/operations{path}", body, self.token, ok)

    def identity(self, method: str, path: str, body: Any = None) -> Any:
        return self.api.call(method, f"/identity/tenant{path}", body, self.token)

    # ------------------------------------------------------------ steps --

    def run(self) -> str:
        s = self.spec
        first, _ = s["locations"][0]
        # Businesses are opened by Tenantly (the admin console, or this command), never by their owner.
        tenant = open_business(self.identity_container, s["name"], first, s["industry"], s["currency"])
        self.slug, self.tenant_id = tenant["slug"], tenant["id"]
        self.enter()
        print(f"\n▸ {s['name']} ({self.slug})")
        self.tree()
        self.enter()  # the token lists the new locations
        self.team()
        self.policies()
        self.catalog()
        self.staff_and_things()
        self.people()
        self.upcoming()
        return self.tenant_id

    def tree(self) -> None:
        org = next(n for n in self.context["nodes"] if n["kind"] == "org")
        self.locations: dict[str, str] = {
            n["name"]: n["id"] for n in self.context["nodes"] if n["kind"] == "location"
        }
        areas: dict[str, str] = {}
        for name, area in self.spec["locations"][1:]:
            parent = org["id"]
            if area:
                if area not in areas:
                    areas[area] = self.identity("POST", "/nodes", {"parentId": org["id"], "kind": "region", "name": area})["id"]
                parent = areas[area]
            self.locations[name] = self.identity("POST", "/nodes", {"parentId": parent, "kind": "location", "name": name})["id"]
        opens, closes = self.spec["hours"]
        for name, node_id in self.locations.items():
            place: dict[str, Any] = {}
            if name in PLACES:
                address, lat, lng = PLACES[name]
                place = {"address": address, "lat": lat, "lng": lng}
            self.identity("PATCH", f"/nodes/{node_id}", {"tz": self.spec["tz"], "open": opens, "close": closes, **place})
        print(f"  {len(self.locations)} locations, {len(areas)} areas")

    def team(self) -> None:
        org = next(n for n in self.context["nodes"] if n["kind"] == "org")
        sites = list(self.locations.values())
        for i, (role, name) in enumerate(self.spec["team"]):
            scope = sites[i % len(sites)] if role == "location_manager" else org["id"]
            if role == "regional_manager":
                scope = next((n["id"] for n in self.context["nodes"] if n["kind"] == "region"), org["id"])
            email = slug_email(name, self.spec["name"])
            # The owner creates their account; someone who already has one (another demo business) is invited.
            body = {"email": email, "role": role, "scopeId": scope, "name": name, "password": PASSWORD}
            added = self.identity("POST", "/members", body)
            if added.get("invite"):
                account(self.api, email, added["invite"])
        print(f"  {len(self.spec['team'])} team members added")

    def policies(self) -> None:
        org = next(n for n in self.context["nodes"] if n["kind"] == "org")
        for key, value in self.spec["policies"].items():
            self.ops("PUT", "/policies", {"scope": org["id"], "key": key, "value": value})
        if site := self.spec.get("approval_at"):
            self.ops("PUT", "/policies", {"scope": self.locations[site], "key": "booking.approval", "value": True})

    def catalog(self) -> None:
        self.offerings: list[dict[str, Any]] = []
        for kind, name, category, price, extra in self.spec["offerings"]:
            self.offerings.append(
                self.ops("POST", "/offerings", {"kind": kind, "name": name, "category": category, "price": price, **extra})
            )
        print(f"  {len(self.offerings)} offerings")

    def staff_and_things(self) -> None:
        self.resources: dict[str, list[dict[str, Any]]] = {}
        used = set()
        for site, location_id in self.locations.items():
            here = self.resources.setdefault(location_id, [])
            for kind, role, names in self.spec["resources"]:
                if isinstance(names, int):
                    picked = []
                    while len(picked) < names:
                        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
                        if name not in used:
                            used.add(name)
                            picked.append(name)
                    names = picked
                for name in names:
                    here.append(
                        self.ops("POST", "/resources", {"locationId": location_id, "type": kind, "name": name, "role": role})
                    )
            # One thing out of service somewhere, so the Resources page shows it.
            if site == list(self.locations)[0] and len(here) > 3:
                assets = [r for r in here if r["type"] == "asset"]
                if assets:
                    self.ops("POST", f"/resources/{assets[-1]['id']}/status", {"status": "out_of_service"})
        print(f"  {sum(len(v) for v in self.resources.values())} resources")

    def people(self) -> None:
        self.customers: dict[str, list[str]] = {loc: [] for loc in self.locations.values()}
        sites = list(self.locations.values())
        plans = [o for o in self.offerings if o["time"] == "none"]
        accounts: list[tuple[str, str]] = []
        if self.spec.get("accounts"):
            for name in ("Lakeview Dental", "Northwind Offices", "Maple Court HOA", "Riverside Co-working"):
                loc = random.choice(sites)
                accounts.append((self.ops("POST", "/accounts", {"locationId": loc, "type": "business", "name": name})["id"], loc))
        names: set[str] = set()
        sold = waivers = 0
        today = datetime.now(self.tz).date()
        while len(names) < self.spec["customers"]:
            names.add(f"{random.choice(FIRST)} {random.choice(LAST)}")
        for i, name in enumerate(sorted(names, key=lambda _: random.random())):
            loc = sites[i % len(sites)] if random.random() < 0.8 else random.choice(sites)
            body: dict[str, Any] = {
                "locationId": loc,
                "name": name,
                "phone": f"+1 555 {random.randint(100, 999)} {random.randint(1000, 9999)}",
                "email": f"{name.lower().replace(' ', '.')}@example.com",
            }
            if accounts and random.random() < 0.25:
                account_id, loc = random.choice(accounts)
                body |= {"locationId": loc, "accountId": account_id, "accountRole": random.choice(["Office manager", "Facilities", "Owner"])}
            elif self.spec.get("accounts") and random.random() < 0.2:
                body |= {"accountType": "household", "accountName": f"{name.split()[1]} household", "accountRole": "Homeowner"}
            customer = self.ops("POST", "/customers", body)["id"]
            self.customers[loc].append(customer)
            if plans and random.random() < self.spec["plan_share"]:
                self.ops("POST", f"/customers/{customer}/plan", {"offeringId": random.choice(plans)["id"]})
                sold += 1
            if self.spec.get("waivers") and random.random() < 0.85:
                issued = today - timedelta(days=random.randint(0, 300))
                self.ops("POST", f"/customers/{customer}/documents", {"type": "waiver", "issued": issued.isoformat()})
                waivers += 1
        print(f"  {len(names)} customers, {len(accounts)} companies, {sold} plans sold" + (f", {waivers} waivers" if waivers else ""))

    def upcoming(self) -> None:
        """The next week: single bookings and class sessions, joined by customers."""
        opens, closes = self.spec["hours"]
        now = datetime.now(self.tz)
        singles = [o for o in self.offerings if o["time"] != "none" and (o.get("capacity") or 1) <= 1]
        shared = [o for o in self.offerings if o["time"] == "slot" and (o.get("capacity") or 1) > 1]
        booked = sessions = seats = 0
        for location_id, here in self.resources.items():
            regulars = self.customers[location_id] or [c for v in self.customers.values() for c in v]
            for offering in shared:
                instructors = matching(here, offering["requires"], "staff")
                if not instructors:
                    continue
                for slot in random.sample(range(opens, closes - offering["minutes"], 60), 2):
                    day = now.date() + timedelta(days=random.randint(0, 2))
                    start = stamp(day, slot)
                    if datetime.fromisoformat(start).replace(tzinfo=self.tz) <= now:
                        day += timedelta(days=1)
                        start = stamp(day, slot)
                    staff = random.choice(instructors)["id"]
                    made = self.ops(
                        "POST",
                        "/sessions",
                        {"locationId": location_id, "offeringId": offering["id"], "staffId": staff, "start": start, "repeatWeeks": 2},
                        ok=(409, 422),
                    )
                    sessions += (made or {}).get("created", 0)
            options = self.ops("GET", f"/booking-options?location={location_id}")
            for session in options["sessions"]:
                capacity = session.get("capacity") or 10
                for customer in random.sample(regulars, min(len(regulars), random.randint(capacity // 3, capacity))):
                    if self.ops("POST", f"/bookings/{session['id']}/attendees", {"customerId": customer}, ok=(403, 409, 422)) is not None:
                        seats += 1
            for _ in range(self.spec["per_day"] * 6):
                offering = random.choice(singles) if singles else None
                if not offering:
                    break
                day = now.date() + timedelta(days=random.randint(0, 6))
                length = offering["minutes"] or 60
                latest = closes - length
                if latest <= opens:
                    continue
                minute = random.randrange(opens, latest, 30)
                start_dt = datetime.combine(day, datetime.min.time(), self.tz) + timedelta(minutes=minute)
                if start_dt <= now:
                    continue
                pick = matching(here, offering["requires"], "staff")
                body = {
                    "locationId": location_id,
                    "offeringId": offering["id"],
                    "customerId": random.choice(regulars),
                    "start": stamp(day, minute),
                }
                if pick:
                    body["staffId"] = random.choice(pick)["id"]
                if offering["unit"] == "day":
                    body["units"] = random.randint(1, 3)
                if self.ops("POST", "/bookings", body, ok=(403, 409, 422)) is not None:
                    booked += 1
        print(f"  next 7 days: {booked} bookings, {sessions} class sessions, {seats} seats taken")


def stamp(day: date, minute: int) -> str:
    return f"{day.isoformat()}T{minute // 60:02d}:{minute % 60:02d}"


def matching(resources: list[dict[str, Any]], requires: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """The resources that fill the offering's requirement of this type (by role)."""
    need = next((r for r in requires if r["type"] == kind and r.get("quantity")), None)
    if not need:
        return []
    role = (need.get("role") or "").lower()
    return [r for r in resources if r["type"] == kind and (not role or r["role"].lower() == role) and r["status"] == "available"]


def engine() -> str | None:
    return shutil.which("podman") or shutil.which("docker")


def in_container(container: str, *args: str) -> str:
    """Run a manage.py command in a service's container; its output, or why it failed."""
    runner = engine()
    if not runner:
        return f"! no podman/docker: run `manage.py {' '.join(args)}` in {container} yourself"
    result = subprocess.run([runner, "exec", container, "python", "manage.py", *args], capture_output=True, text=True, check=False)  # noqa: S603
    return (result.stdout or result.stderr).strip()


def open_business(container: str, name: str, location: str, industry: str, currency: str) -> dict[str, Any]:
    """`manage.py open_business` for the demo owner (created on first use); the business as JSON."""
    out = in_container(
        container, "open_business", OWNER[1], name, "--location", location, "--industry", industry,
        "--currency", currency, "--name", OWNER[0], "--password", PASSWORD,
    )  # fmt: skip
    try:
        return json.loads(out.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        raise RuntimeError(f"open_business {name!r}: {out}") from None


def ensure_owner(container: str) -> None:
    """The demo owner's account, made the way Tenantly makes owners' accounts (no sign-up)."""
    script = (
        "from src.models import User; from src.services import accounts; "
        f"User.objects.filter(email={OWNER[1]!r}).exists() or accounts.create_account({OWNER[0]!r}, {OWNER[1]!r}, {PASSWORD!r})"
    )
    in_container(container, "shell", "-c", script)


def history(tenant_id: str, spec: dict[str, Any], days: int, container: str) -> None:
    opens, closes = spec["hours"]
    out = in_container(
        container, "seed_history",
        "--tenant", tenant_id, "--tz", spec["tz"], "--currency", spec["currency"], "--days", str(days),
        "--open", str(opens), "--close", str(closes), "--per-day", str(spec["per_day"]),
    )  # fmt: skip
    print(f"  history: {out}")


def plan(slug: str, spec: dict[str, Any], container: str) -> None:
    name, terms = spec["plan"]
    flags = [f"--{k}={v}" for k, v in terms.items()]
    print(f"  plan: {in_container(container, 'set_plan', slug, name, *flags)}")


# Deletes every row of one business in a service: rows that others still point at
# (PROTECT) go on a later pass.
FORGET = """
from django.apps import apps
from django.db.models import ProtectedError
models = [m for m in apps.get_app_config({app!r}).get_models() if any(f.attname == "tenant_id" for f in m._meta.fields)]
for _ in range(len(models) + 1):
    left = 0
    for m in models:
        try:
            m.objects.filter(tenant_id={tenant!r}).delete()
        except ProtectedError:
            left += 1
    if not left:
        break
"""
FORGET_TENANT = """
from src.models import Membership, Tenant
Membership.objects.filter(tenant_id={tenant!r}).delete()
Tenant.objects.filter(id={tenant!r}).delete()
"""


def forget(tenant_id: str, containers: dict[str, str]) -> None:
    """Remove a demo business from every service, so it can be seeded again."""
    for app in ("operations", "billing"):
        in_container(containers[app], "shell", "-c", FORGET.format(app=app, tenant=tenant_id))
    in_container(containers["identity"], "shell", "-c", FORGET_TENANT.format(tenant=tenant_id))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8080/api")
    parser.add_argument("--days", type=int, default=90, help="Days of history to write (default 90).")
    parser.add_argument("--container", default="tenantly-operations-1")
    parser.add_argument("--identity-container", default="tenantly-identity-1")
    parser.add_argument("--billing-container", default="tenantly-billing-1")
    parser.add_argument("--reset", action="store_true", help="Delete the demo businesses first and seed them anew.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed)
    containers = {"operations": args.container, "identity": args.identity_container, "billing": args.billing_container}

    api = Api(args.api)
    ensure_owner(args.identity_container)
    session = account(api, OWNER[1])
    demo = {spec["name"] for spec in BUSINESSES}
    existing = {
        w["tenant"]["name"]: w["tenant"]
        for w in api.call("GET", "/identity/me/workspaces", token=session)
        if w["tenant"]["name"] in demo
    }
    if args.reset:
        for name, tenant in existing.items():
            forget(tenant["id"], containers)
            print(f"▸ {name}: deleted")
        existing = {}
    for spec in BUSINESSES:
        if spec["name"] in existing:
            print(f"\n▸ {spec['name']}: already there, skipped")
            plan(existing[spec["name"]]["slug"], spec, args.identity_container)
            continue
        try:
            seeder = Seeder(api, spec, session, args.identity_container)
            tenant_id = seeder.run()
        except RuntimeError as exc:
            sys.exit(f"  ✗ {exc}\n  Run again with --reset to start the demo businesses over.")
        plan(seeder.slug, spec, args.identity_container)
        history(tenant_id, spec, args.days, args.container)
    print(f"\nDone. Sign in at http://localhost:8080 as {OWNER[1]} / {PASSWORD}")


if __name__ == "__main__":
    main()
