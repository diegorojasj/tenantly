"""Read models for Today, Calendar and Insights (docs/USAGE.md §3)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from common.money import ZERO, dec, label, wire

from ..models import Booking, Customer, Offering, PolicyOverride, Resource
from . import clock, documents, downtimes, fulfilment, money, shape

if TYPE_CHECKING:
    from datetime import datetime

    from common.auth import TenantClaims

WORK = ("bookings.manage", "analytics.view")
ARRIVAL_WINDOW = timedelta(hours=3)
# Hired by the hour or by the day: overdue when still out after its end.
RETURNED = {Offering.Time.WINDOW, Offering.Time.SPAN}


def _weight(b: Booking) -> int:
    return 1 if b.customer_id else len(b.attendances.all())


def _open_minutes(claims: TenantClaims, location_id: str) -> int:
    opens, closes = claims.hours(location_id)
    return closes - opens


def _utilization(claims: TenantClaims, locations: set[str], kind: str, first: date, last: date) -> int:
    """Booked share of open time: `kind` "staff" counts the template's people types, "asset" every other type."""
    team = fulfilment.people(claims)
    rows = Resource.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations, status="available")
    pool = list(rows.filter(type__in=team) if kind == "staff" else rows.exclude(type__in=team))
    if not pool:
        return 0
    ids = {r.id for r in pool}
    days = (last - first).days + 1
    capacity = sum(_open_minutes(claims, str(r.location_id)) for r in pool) * days
    booked = 0.0
    rows = (
        Booking.objects.filter(clock.within_days(claims, locations, first, last), tenant_id=claims.tenant_id)
        .exclude(status=Booking.Status.CANCELLED)
        .prefetch_related("resources")
    )
    for b in rows:
        minutes = (b.end - b.start).total_seconds() / 60
        booked += minutes * sum(1 for r in b.resources.all() if r.id in ids)
    return round(booked / capacity * 100) if capacity else 0


# ---------------------------------------------------------------- today --


def _setup(claims: TenantClaims) -> dict[str, Any]:
    """What a new business still has to do before its first booking (USAGE §6)."""
    tid = claims.tenant_id
    steps = {
        "catalog": Offering.objects.filter(tenant_id=tid).exists(),
        "team": Resource.objects.filter(tenant_id=tid, type__in=fulfilment.people(claims)).exists(),
        "customers": Customer.objects.filter(tenant_id=tid).exists(),
        "policies": PolicyOverride.objects.filter(tenant_id=tid).exists(),
        "bookings": Booking.objects.filter(tenant_id=tid).exists(),
    }
    # Reviewing policies is recommended, not required: the template's defaults are sensible.
    return {"steps": steps, "done": all(v for k, v in steps.items() if k != "policies")}


def _at(claims: TenantClaims, b: Booking, value: datetime) -> str:
    """`HH:MM` on the booking's location clock; `YYYY-MM-DD HH:MM` when it isn't today there."""
    tz = claims.zone(str(b.location_id))
    when = clock.stamp(value, tz)
    return when[11:] if when[:10] == clock.today(tz).isoformat() else when.replace("T", " ")


def _alert(id_: str, tone: str, title: str, detail: str, to: str) -> dict[str, str]:
    return {"id": id_, "tone": tone, "title": title, "detail": detail, "to": to}


def _either(words: list[str]) -> str:
    """ "a or b or c", worded in the request's language."""
    out = words[0]
    for other in words[1:]:
        out = _("%(first)s or %(second)s") % {"first": out, "second": other}
    return out


def _downtime_alerts(claims: TenantClaims, locations: set[str]) -> list[dict[str, Any]]:
    """Bookings a downtime has put in doubt (the desk has to act), and what is unavailable right now."""
    t = claims.template
    now = clock.now()
    out: list[dict[str, Any]] = []
    clashing = downtimes.flags(
        claims,
        list(
            shape.with_relations(
                Booking.objects.filter(
                    tenant_id=claims.tenant_id, location_id__in=locations, status__in=downtimes.LIVE, end__gt=now
                )
            )
        ),
    )
    if clashing:
        noun = t["terms"]["booking" if len(clashing) == 1 else "bookings"].lower()
        out.append(
            _alert(
                "clashes",
                "bad",
                _("%(n)s %(bookings)s fall in a downtime") % {"n": len(clashing), "bookings": noun},
                " · ".join(sorted({downtimes.describe(claims, d) for d in clashing.values()})[:3]),
                "bookings",
            )
        )
    unavailable = downtimes.current(claims, locations)
    if unavailable:
        out.append(
            _alert(
                "unavailable",
                "warn",
                ngettext("%(n)s unavailable now", "%(n)s unavailable now", len(unavailable)) % {"n": len(unavailable)},
                " · ".join(downtimes.describe(claims, d) for d in unavailable[:3]),
                "resources",
            )
        )
    return out


def _alerts(
    claims: TenantClaims, live: list[Booking], arrivals: list[Booking], locations: set[str]
) -> list[dict[str, Any]]:
    t = claims.template
    now = clock.now()
    alerts: list[dict[str, Any]] = []
    requests = Booking.objects.filter(
        tenant_id=claims.tenant_id, location_id__in=locations, status="requested", start__gte=now
    ).count()
    if requests:
        noun = t["terms"]["booking" if requests == 1 else "bookings"].lower()
        alerts.append(
            _alert(
                "requests",
                "warn",
                _("%(n)s %(status)s %(bookings)s")
                % {"n": requests, "status": t["status"]["requested"].lower(), "bookings": noun},
                _("Confirm or decline them so the slot isn't lost."),
                "bookings",
            )
        )
    overdue = [b for b in live if b.status == "checked_in" and b.end < now and b.offering.time in RETURNED]
    if overdue:
        detail = " · ".join(
            _("%(resources)s due %(when)s")
            % {"resources": ", ".join(r.name for r in b.resources.all()), "when": _at(claims, b, b.end)}
            for b in overdue[:3]
        )
        title = ngettext("%(n)s not returned on time", "%(n)s not returned on time", len(overdue)) % {"n": len(overdue)}
        alerts.append(_alert("overdue", "bad", title, detail, "bookings"))
    arriving: dict[str, Customer] = {}
    lacking: dict[str, set[str]] = {}  # customer -> labels of documents the policy asks for
    rules: dict[str, dict[str, str]] = {}
    for b in arrivals:
        loc = str(b.location_id)
        if loc not in rules:
            rules[loc] = documents.rules_at(claims, loc)
        day = clock.local(b.start, claims.zone(loc)).date()
        for c in [b.customer] if b.customer else [a.customer for a in b.attendances.all()]:
            arriving[str(c.id)] = c
            if rules[loc]:
                gaps = documents.missing(claims, c, day, rules[loc], subject=b.subject if b.customer else None)
                if gaps:
                    lacking.setdefault(str(c.id), set()).update(k["label"].lower() for k in gaps)
    if lacking:
        labels = sorted({label for gaps in lacking.values() for label in gaps})
        either = _either(labels)
        alerts.append(
            _alert(
                "documents",
                "warn",
                ngettext(
                    "%(n)s arriving without a valid %(documents)s",
                    "%(n)s arriving without a valid %(documents)s",
                    len(lacking),
                )
                % {"n": len(lacking), "documents": either},
                ", ".join(arriving[cid].name for cid in list(lacking)[:3]),
                "customers",
            )
        )
    if arriving:
        owing = {
            cid: dec(m["balance"]) for cid, m in money.balances(claims, list(arriving)).items() if dec(m["balance"]) > 0
        }
        if owing:
            alerts.append(
                _alert(
                    "balance",
                    "warn",
                    ngettext("%(n)s arriving with an open balance", "%(n)s arriving with an open balance", len(owing))
                    % {"n": len(owing)},
                    _("%(amount)s to collect at the desk")
                    % {"amount": label(sum(owing.values(), ZERO), claims.currency)},
                    "payments",
                )
            )
    full = [
        b for b in live if not b.customer_id and len(b.attendances.all()) >= (b.offering.capacity or 0) and b.end > now
    ]
    if full:
        alerts.append(
            _alert(
                "full",
                "info",
                ngettext("%(n)s full session today", "%(n)s full sessions today", len(full)) % {"n": len(full)},
                " · ".join(f"{b.offering.name} {_at(claims, b, b.start)}" for b in full[:3]),
                "calendar",
            )
        )
    alerts.extend(_downtime_alerts(claims, locations))
    down = list(Resource.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations, status="out_of_service"))
    if down:
        alerts.append(
            _alert(
                "down",
                "info",
                ngettext("%(n)s out of service", "%(n)s out of service", len(down)) % {"n": len(down)},
                ", ".join(r.name for r in down[:4]),
                "resources",
            )
        )
    return alerts


def today(claims: TenantClaims, scope: str | None) -> dict[str, Any]:
    claims.demand_any(WORK)
    locations = claims.locations(scope)
    day = clock.today(clock.zone_of(claims, locations))
    now = clock.now()
    live = list(
        shape.with_relations(
            Booking.objects.filter(
                clock.within_days(claims, locations, day, day, overlap=True), tenant_id=claims.tenant_id
            )
        ).exclude(status=Booking.Status.CANCELLED)
    )
    arrivals = [
        b for b in live if b.status in {"confirmed", "requested"} and b.end > now and b.start <= now + ARRIVAL_WINDOW
    ][:12]
    in_progress = sorted((b for b in live if b.status == "checked_in"), key=lambda b: b.end)
    revenue = money.revenue(claims, locations, day, day) if locations else {"byDay": {}}
    return {
        "day": day.isoformat(),
        "kpis": {
            "bookings": len(live),
            "expected": sum(_weight(b) for b in live),
            "checkedIn": sum(_weight(b) for b in live if b.status in {"checked_in", "completed"}),
            "revenue": wire(sum((dec(v) for v in revenue["byDay"].values()), ZERO)),
            "utilization": _utilization(claims, locations, "staff", day, day),
        },
        "arrivals": shape.bookings(claims, arrivals),
        "inProgress": shape.bookings(claims, in_progress),
        "alerts": _alerts(claims, live, arrivals, locations),
        "setup": _setup(claims),
    }


# ------------------------------------------------------------- calendar --


def calendar(claims: TenantClaims, scope: str | None, day_value: str | None) -> dict[str, Any]:
    claims.demand_any(WORK)
    focus = claims.node(claims.focus(scope))
    locations = claims.locations(scope)
    tz = clock.zone_of(claims, locations)
    day = clock.parse_day(day_value, tz)
    rows = list(
        shape.with_relations(
            Booking.objects.filter(
                clock.within_days(claims, locations, day, day, overlap=True), tenant_id=claims.tenant_id
            )
        ).exclude(status=Booking.Status.CANCELLED)
    )
    # A location's board runs on its own hours; an overview on the template's.
    opens, closes = claims.hours(focus.id if focus and focus.kind == "location" else None)
    base = {
        "date": day.isoformat(),
        "today": clock.today(tz).isoformat(),
        "open": opens,
        "close": closes,
        "tz": tz.key,
    }
    if not focus or focus.kind != "location":
        sites = []
        for node in (n for n in claims.nodes if n.id in locations):
            mine = [b for b in rows if str(b.location_id) == node.id]
            sites.append(
                {
                    "node": {
                        "id": node.id,
                        "name": node.name,
                        "kind": node.kind,
                        "parentId": node.parent_id,
                        "code": "",
                        "status": "active",
                    },
                    "bookings": len(mine),
                    "utilization": _utilization(claims, {node.id}, "staff", day, day),
                }
            )
        return {**base, "board": None, "sites": sites}
    return {
        **base,
        "board": {
            "resources": [
                shape.resource(r) for r in Resource.objects.filter(tenant_id=claims.tenant_id, location_id=focus.id)
            ],
            "bookings": shape.bookings(claims, rows),
            # Shaded on the timeline: a resource's row, or (offering and location-wide) the whole board.
            "downtimes": downtimes.at(claims, focus.id, clock.at(day, 0, tz), clock.at(day + timedelta(days=1), 0, tz)),
        },
        "sites": [],
    }


# ------------------------------------------------------------- insights --


def _active(rows: list[Booking]) -> set[str]:
    ids: set[str] = set()
    for b in rows:
        if b.status == "completed":
            ids |= {str(b.customer_id)} if b.customer_id else {str(a.customer_id) for a in b.attendances.all()}
    return ids


def _no_show(rows: list[Booking]) -> float:
    singles = [b for b in rows if b.customer_id and b.status in {"completed", "no_show"}]
    return round(sum(b.status == "no_show" for b in singles) / len(singles) * 100, 1) if singles else 0.0


def insights(claims: TenantClaims, scope: str | None, days: int) -> dict[str, Any]:
    claims.demand("analytics.view")
    span = 7 if days == 7 else 28  # noqa: PLR2004
    locations = claims.locations(scope)
    last = clock.today(clock.zone_of(claims, locations))
    first = last - timedelta(days=span - 1)
    prev_last = first - timedelta(days=1)
    prev_first = prev_last - timedelta(days=span - 1)
    before_first = prev_first - timedelta(days=span)

    rows = list(
        Booking.objects.filter(clock.within_days(claims, locations, before_first, last), tenant_id=claims.tenant_id)
        .select_related("offering")
        .prefetch_related("attendances")
    )

    def period(a: date, b: date) -> list[Booking]:
        return [r for r in rows if a <= clock.local(r.start, claims.zone(str(r.location_id))).date() <= b]

    cur, prev, older = (
        period(first, last),
        period(prev_first, prev_last),
        period(before_first, prev_first - timedelta(days=1)),
    )

    def retention(before: list[Booking], after: list[Booking]) -> int | None:
        came, back = _active(before), _active(after)
        return round(len(came & back) / len(came) * 100) if came else None

    revenue = money.revenue(claims, locations, prev_first, last) if locations else {"byDay": {}, "byLocation": {}}
    by_day = {d: dec(v) for d, v in revenue["byDay"].items()}
    current_by_location = money.revenue(claims, locations, first, last)["byLocation"] if locations else {}

    top: dict[str, dict[str, Any]] = {}
    for b in cur:
        if b.status != "completed":
            continue
        entry = top.setdefault(
            str(b.offering_id), {"name": b.offering.name, "kind": b.offering.kind, "revenue": ZERO, "bookings": 0}
        )
        entry["bookings"] += 1
        entry["revenue"] += b.price * (1 if b.customer_id else len(b.attendances.all()))

    new_customers = Customer.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations)
    return {
        "days": span,
        "revenue": {
            "total": wire(sum((v for d, v in by_day.items() if d >= first.isoformat()), ZERO)),
            "previous": wire(sum((v for d, v in by_day.items() if d < first.isoformat()), ZERO)),
            "series": [wire(by_day.get((first + timedelta(days=i)).isoformat(), ZERO)) for i in range(span)],
        },
        "utilization": {
            "staff": _utilization(claims, locations, "staff", first, last),
            "assets": _utilization(claims, locations, "asset", first, last),
            "previousStaff": _utilization(claims, locations, "staff", prev_first, prev_last),
            "previousAssets": _utilization(claims, locations, "asset", prev_first, prev_last),
        },
        "noShowRate": {"value": _no_show(cur), "previous": _no_show(prev)},
        "retention": {"value": retention(prev, cur) or 0, "previous": retention(older, prev)},
        "newCustomers": {
            "value": new_customers.filter(since__gte=first, since__lte=last).count(),
            "previous": new_customers.filter(since__gte=prev_first, since__lte=prev_last).count(),
        },
        "topOfferings": sorted(
            ({**v, "revenue": wire(v["revenue"])} for v in top.values()), key=lambda v: -dec(v["revenue"])
        )[:6],
        "locations": sorted(
            (
                {
                    "id": node.id,
                    "name": node.name,
                    "revenue": wire(current_by_location.get(node.id)),
                    "utilization": _utilization(claims, {node.id}, "staff", first, last),
                }
                for node in claims.nodes
                if node.id in locations
            ),
            key=lambda x: -dec(x["revenue"]),
        ),
    }
