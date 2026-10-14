#!/usr/bin/env python3
"""Seed the demo businesses with unavailability and the ledger, through the same APIs the app uses.

For each business the demo owner holds (seed_demo.py in English, seed_demo_es.py in
Spanish), it records:

- a repair happening now on one asset, with its bill (parts, labour) and the damage
  charged to the customer who caused it;
- maintenance next week on another asset;
- a team member away tomorrow, so the bookings they already had are flagged;
- one offering unsuitable for use for a few days at the second location (if any);
- a power cut that is already over, with what it cost and the insurance paid back;
- the month's running costs and other income on the Payments page (rent, supplies…).

    python3 scripts/seed_downtime.py              # English businesses (demo@tenantly.dev)
    python3 scripts/seed_downtime.py --lang es    # Spanish businesses (demo.es@tenantly.dev)

Both seed scripts run it at the end. A business that already has downtime is skipped.
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import seed_demo as base

OWNERS = {"en": "demo@tenantly.dev", "es": "demo.es@tenantly.dev"}

TEXT: dict[str, dict[str, Any]] = {
    "en": {
        "repair": "Leaking seal, waiting for parts",
        "parts": ("Parts", "Replacement seal and fittings"),
        "labour": ("Labour", "Technician, 3 hours"),
        "damage": ("Damage", "Damage charged to the customer"),
        "maintenance": "Scheduled service",
        "absence": "Sick leave",
        "unfit": "Failed safety check, out until re-inspected",
        "closure": "Power cut in the building",
        "generator": ("Generator", "Generator rental for the afternoon"),
        "insurance": ("Insurance", "Insurance payout for the power cut"),
        "ledger": [
            ("expense", "Rent", "Monthly rent", (1800, 4200), 2),
            ("expense", "Utilities", "Electricity and water", (220, 540), 6),
            ("expense", "Supplies", "Cleaning and consumables", (80, 260), 12),
            ("expense", "Marketing", "Local ads", (150, 400), 18),
            ("income", "Sublease", "Corner rented to a coffee cart", (300, 600), 9),
            ("income", "Rebate", "Supplier volume rebate", (60, 180), 22),
        ],
    },
    "es": {
        "repair": "Fuga en un sello, esperando repuestos",
        "parts": ("Repuestos", "Sello y conexiones de reemplazo"),
        "labour": ("Mano de obra", "Técnico, 3 horas"),
        "damage": ("Daños", "Daño cobrado al cliente"),
        "maintenance": "Servicio programado",
        "absence": "Licencia por enfermedad",
        "unfit": "No pasó la revisión de seguridad, fuera hasta reinspección",
        "closure": "Corte de luz en el edificio",
        "generator": ("Generador", "Alquiler de generador por la tarde"),
        "insurance": ("Seguro", "Reembolso del seguro por el corte de luz"),
        "ledger": [
            ("expense", "Alquiler", "Alquiler del mes", (1800, 4200), 2),
            ("expense", "Servicios", "Luz y agua", (220, 540), 6),
            ("expense", "Insumos", "Limpieza y consumibles", (80, 260), 12),
            ("expense", "Publicidad", "Anuncios locales", (150, 400), 18),
            ("income", "Subarriendo", "Esquina alquilada a un carrito de café", (300, 600), 9),
            ("income", "Bonificación", "Bonificación por volumen del proveedor", (60, 180), 22),
        ],
    },
}

# Currencies whose amounts are large numbers: demo amounts are scaled so they look real.
SCALE = {"CLP": 900, "COP": 4000, "MXN": 18, "PEN": 4, "BOB": 7}


def stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


class Business:
    def __init__(self, api: base.Api, session: str, tenant: dict[str, Any], lang: str) -> None:
        self.api, self.session, self.tenant, self.t = api, session, tenant, TEXT[lang]
        entered = api.call("POST", f"/identity/tenants/{tenant['slug']}/token", {"scope": None}, session)
        self.token = entered["token"]
        self.scale = SCALE.get(tenant.get("currency") or "USD", 1)

    def ops(self, method: str, path: str, body: Any = None, ok: tuple[int, ...] = ()) -> Any:
        return self.api.call(method, f"/operations{path}", body, self.token, ok)

    def billing(self, method: str, path: str, body: Any = None) -> Any:
        return self.api.call(method, f"/billing{path}", body, self.token)

    def amount(self, low: float, high: float) -> str:
        return f"{round(random.uniform(low, high) * self.scale, 2):.2f}"

    def down(self, body: dict[str, Any]) -> dict[str, Any] | None:
        return self.ops("POST", "/downtimes", body, ok=(404, 409, 422))

    def money(self, downtime: dict[str, Any] | None, kind: str, label: tuple[str, str], low: float, high: float, **extra: Any) -> None:
        if downtime:
            category, description = label
            body = {"kind": kind, "amount": self.amount(low, high), "category": category, "description": description, **extra}
            self.ops("POST", f"/downtimes/{downtime['id']}/money", body, ok=(403, 422))

    def run(self) -> None:
        name = self.tenant["name"]
        self.has_downtime = bool(self.ops("GET", "/downtimes")["downtimes"])
        self.has_ledger = any(e["source"] == "manual" for e in self.billing("GET", "/ledger")["entries"])
        if self.has_downtime and self.has_ledger:
            print(f"  {name}: already seeded, skipped")
            return
        rows = self.ops("GET", "/resources")["resources"]
        sites = [loc["id"] for loc in self.ops("GET", "/resources")["locations"]]
        if not rows or not sites:
            print(f"  {name}: no resources, skipped")
            return
        by_site: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            if r["resource"]["status"] == "available":
                by_site.setdefault(r["resource"]["locationId"], []).append(r["resource"])
        first = next((s for s in sites if by_site.get(s)), sites[0])
        here = by_site.get(first, [])
        tz = ZoneInfo(self.ops("GET", f"/booking-options?location={first}")["tz"])
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        made = 0
        if not self.has_downtime:
            made = self.downtimes(rows, sites, by_site, first, here, today)
        lines = 0 if self.has_ledger else self.ledger(sites, first, today)
        print(f"  {name}: {made} downtimes, {lines} ledger lines")

    def downtimes(self, rows: list[dict[str, Any]], sites: list[str], by_site: dict[str, list[dict[str, Any]]],
                  first: str, here: list[dict[str, Any]], today: datetime) -> int:  # fmt: skip
        things = [r for r in here if r["type"] != "staff"] or here
        team = [r for r in here if r["type"] == "staff"]
        made = 0

        # A repair going on now, its bill, and the damage charged to whoever caused it.
        repair = self.down({"resourceId": things[0]["id"], "reason": "repair", "note": self.t["repair"],
                            "end": stamp(today + timedelta(days=2, hours=18))})  # fmt: skip
        self.money(repair, "expense", self.t["parts"], 60, 180)
        self.money(repair, "expense", self.t["labour"], 90, 240)
        customers = self.ops("GET", f"/booking-options?location={first}")["customers"]
        if customers:
            self.money(repair, "income", self.t["damage"], 40, 120, customerId=random.choice(customers)["id"])
        made += bool(repair)

        # Maintenance next week on another one.
        if len(things) > 1:
            start = today + timedelta(days=6, hours=8)
            made += bool(self.down({"resourceId": things[1]["id"], "reason": "maintenance", "note": self.t["maintenance"],
                                    "start": stamp(start), "end": stamp(start + timedelta(days=1, hours=10))}))  # fmt: skip

        # Someone away tomorrow: their bookings stay, flagged for the desk.
        busiest = max(
            (r for r in rows if r["resource"]["type"] == "staff" and r["resource"]["status"] == "available" and r["next"]),
            key=lambda r: r["utilization"],
            default=None,
        )
        away = busiest["resource"] if busiest else (team[0] if team else None)
        if away:
            start = today + timedelta(days=1)
            made += bool(self.down({"resourceId": away["id"], "reason": "absence", "note": self.t["absence"],
                                    "start": stamp(start), "end": stamp(start + timedelta(days=1))}))  # fmt: skip

        # One offering unsuitable for use at the second location for a few days.
        second = next((s for s in sites if s != first), None)
        if second:
            offerings = self.ops("GET", f"/booking-options?location={second}")["offerings"]
            if offerings:
                start = today + timedelta(days=2)
                made += bool(self.down({"locationId": second, "offeringId": random.choice(offerings)["id"], "reason": "unfit",
                                        "note": self.t["unfit"], "start": stamp(start), "end": stamp(start + timedelta(days=3))}))  # fmt: skip

        # A power cut that's already over: what it cost, and the insurance paid back.
        closure = self.down({"locationId": first, "reason": "closure", "note": self.t["closure"]})
        if closure:
            self.ops("POST", f"/downtimes/{closure['id']}/end", ok=(422,))
            self.money(closure, "expense", self.t["generator"], 120, 300)
            self.money(closure, "income", self.t["insurance"], 100, 250)
            made += 1
        return made

    def ledger(self, sites: list[str], first: str, today: datetime) -> int:
        """The month's running costs and other income, per location."""
        lines = 0
        for site in sites:
            for kind, category, description, (low, high), days_ago in self.t["ledger"]:
                if site != first and category in {"Rent", "Alquiler"} and random.random() < 0.3:
                    continue
                on = (today - timedelta(days=days_ago + random.randint(0, 2))).date().isoformat()
                self.billing("POST", "/ledger", {"locationId": site, "kind": kind, "category": category,
                                                 "description": description, "amount": self.amount(low, high), "on": on})  # fmt: skip
                lines += 1
        return lines


def seed(api: base.Api, session: str, lang: str, names: set[str] | None = None) -> None:
    """Every business the session owns (or only `names`)."""
    print("\n▸ " + ("unavailability and ledger" if lang == "en" else "no disponibilidad y movimientos"))
    for w in api.call("GET", "/identity/me/workspaces", token=session):
        if w["role"] != "owner" or (names is not None and w["tenant"]["name"] not in names):
            continue
        try:
            Business(api, session, w["tenant"], lang).run()
        except RuntimeError as exc:
            print(f"  {w['tenant']['name']}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8080/api")
    parser.add_argument("--lang", choices=("en", "es"), default="en")
    args = parser.parse_args()
    api = base.Api(args.api)
    seed(api, base.account(api, OWNERS[args.lang]), args.lang)


if __name__ == "__main__":
    main()
