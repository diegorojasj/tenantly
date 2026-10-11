"""Fill a demo business with past activity: bookings, class sessions and the money they made.

The API only books from now on, so history for a demo is written here, after
`scripts/seed_demo.py` has set the business up through the API (offerings,
resources, customers, plans). It follows the same rules the booking service does:
resources never double-booked, sessions within capacity, completed bookings
charged on their day, plan members' seats covered, drop-ins paid. Charges go
through the money outbox, so billing records them exactly as it would live ones.

    python manage.py seed_history --tenant <uuid> --tz America/New_York --days 90
"""
# ruff: noqa: S311, PLR2004 - demo data: plain pseudo-random draws and plain odds

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction

from common.money import wire

from ...models import Attendance, Booking, Customer, MoneyEvent, Offering, Resource, Subscription
from ...services.money import dispatch

SLOT = 30
# Share of past single bookings by outcome: completed, no-show, cancelled.
OUTCOMES = (("completed", 0.84), ("no_show", 0.05), ("cancelled", 0.11))
# Classes a regular comes to in a week, on average.
VISITS_PER_WEEK = 2


class Busy:
    """Who is booked when, so generated history never double-books a resource."""

    def __init__(self) -> None:
        self.spans: dict[str, list[tuple[datetime, datetime]]] = {}

    def free(self, resource: Resource, start: datetime, end: datetime) -> bool:
        return all(end <= a or start >= b for a, b in self.spans.get(str(resource.id), []))

    def take(self, resource: Resource, start: datetime, end: datetime) -> None:
        self.spans.setdefault(str(resource.id), []).append((start, end))


def _matches(resources: list[Resource], need: dict[str, Any]) -> list[Resource]:
    role = (need.get("role") or "").lower()
    return [
        r
        for r in resources
        if r.type == need.get("type") and (not role or r.role.lower() == role) and r.status == "available"
    ]


def _pick(
    resources: list[Resource], offering: Offering, busy: Busy, start: datetime, end: datetime
) -> list[Resource] | None:
    """Free resources for every requirement of the offering, or None when it can't run then."""
    chosen: list[Resource] = []
    for need in offering.requires:
        quantity = int(need.get("quantity") or 0)
        if not quantity:
            continue
        pool = [r for r in _matches(resources, need) if r not in chosen and busy.free(r, start, end)]
        if len(pool) < quantity:
            return None
        chosen += random.sample(pool, quantity)
    return chosen


class Command(BaseCommand):
    help = "Write past bookings, class sessions and charges for one demo business."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--tz", default="UTC")
        parser.add_argument("--currency", default="USD")
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--open", type=int, default=8 * 60, help="Opening time, minutes from midnight.")
        parser.add_argument("--close", type=int, default=20 * 60, help="Closing time, minutes from midnight.")
        parser.add_argument("--per-day", type=int, default=8, help="Single bookings per location per day, on average.")
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args: Any, **o: Any) -> None:  # noqa: ARG002
        random.seed(o["seed"])
        self.tenant = o["tenant"]
        self.tz = ZoneInfo(o["tz"])
        self.currency = o["currency"]
        self.open, self.close = o["open"], o["close"]
        self.now = datetime.now(UTC)
        today = self.now.astimezone(self.tz).date()

        offerings = list(Offering.objects.filter(tenant_id=self.tenant, active=True))
        singles = [x for x in offerings if x.time != Offering.Time.NONE and not x.shared]
        sessions = [x for x in offerings if x.time == Offering.Time.SLOT and x.shared]
        resources = list(Resource.objects.filter(tenant_id=self.tenant))
        customers = list(Customer.objects.filter(tenant_id=self.tenant))
        if not customers or not offerings:
            self.stderr.write("Nothing to build on: add offerings and customers first.")
            return

        with transaction.atomic():
            self._backdate_customers(customers, today, o["days"])
            # Plans first: a member's past class seats are covered only once their plan's start
            # date has been moved back; otherwise every member pays a drop-in for each class.
            self._plan_history(today)
            locations = sorted({str(r.location_id) for r in resources})
            counts = {"bookings": 0, "sessions": 0, "seats": 0, "charges": 0}
            for location in locations:
                here = [r for r in resources if str(r.location_id) == location]
                regulars = [c for c in customers if str(c.location_id) == location] or customers
                busy = Busy()
                # Keep today's and future bookings (made through the API) clear.
                for b in Booking.objects.filter(location_id=location, end__gt=self.now).prefetch_related("resources"):
                    for r in b.resources.all():
                        busy.take(r, b.start, b.end)
                timetable = self._timetable(sessions)
                self.fill = self._fill(timetable, regulars)
                for back in range(o["days"], -1, -1):
                    day = today - timedelta(days=back)
                    made, seats = self._sessions(day, location, timetable, here, regulars, busy)
                    counts["sessions"] += made
                    counts["seats"] += seats
                    counts["bookings"] += self._singles(day, location, singles, here, regulars, busy, o["per_day"])
            counts["charges"] = MoneyEvent.objects.filter(tenant_id=self.tenant, sent_at__isnull=True).count()

        sent = 1
        while sent:
            sent = dispatch(limit=1000)
        pending = MoneyEvent.objects.filter(tenant_id=self.tenant, sent_at__isnull=True).count()
        self.stdout.write(
            f"{counts['bookings']} bookings, {counts['sessions']} sessions ({counts['seats']} seats), "
            f"{counts['charges']} charges sent to billing" + (f", {pending} still pending" if pending else "")
        )

    # ----------------------------------------------------------- pieces --

    def _at(self, day: date, minute: int) -> datetime:
        return datetime.combine(day, time(minute // 60, minute % 60), self.tz).astimezone(UTC)

    def _charge(self, customer: Customer, location: str, **body: Any) -> None:
        MoneyEvent.objects.create(
            tenant_id=self.tenant,
            path="/internal/charges",
            body={
                "tenantId": self.tenant,
                "locationId": location,
                "customerId": str(customer.id),
                "customerName": customer.name,
                "currency": self.currency,
                **body,
            },
        )

    def _backdate_customers(self, customers: list[Customer], today: date, days: int) -> None:
        """Regulars joined over the last year or so; a few are new this month."""
        for c in customers:
            c.since = today - timedelta(days=random.choice([random.randint(0, 30), random.randint(days, days + 300)]))
            c.save(update_fields=["since"])

    def _timetable(self, sessions: list[Offering]) -> list[tuple[Offering, int, int]]:
        """Each class runs at a fixed time on a few weekdays: (offering, weekday, minute)."""
        rows = []
        for offering in sessions:
            starts = list(range(self.open, self.close - offering.minutes + 1, 60))
            for minute in random.sample(starts, min(2, len(starts))):
                for weekday in random.sample(range(7), random.randint(3, 5)):
                    rows.append((offering, weekday, minute))
        return rows

    def _fill(self, timetable: list[tuple[Offering, int, int]], regulars: list[Customer]) -> float:
        """How full classes run here, so a regular comes to about two a week, not one a day."""
        weekly_seats = sum((offering.capacity or 1) * 0.7 for offering, _, _ in timetable)
        return min(1.0, VISITS_PER_WEEK * len(regulars) / weekly_seats) if weekly_seats else 1.0

    def _sessions(
        self,
        day: date,
        location: str,
        timetable: list[tuple[Offering, int, int]],
        here: list[Resource],
        regulars: list[Customer],
        busy: Busy,
    ) -> tuple[int, int]:
        made = seats = 0
        for offering, weekday, minute in timetable:
            if day.weekday() != weekday:
                continue
            start = self._at(day, minute)
            end = start + timedelta(minutes=offering.minutes)
            if end > self.now:
                continue  # today's later classes and the future come from the API
            assigned = _pick(here, offering, busy, start, end)
            if assigned is None:
                continue
            session = Booking.objects.create(
                tenant_id=self.tenant,
                location_id=location,
                offering=offering,
                start=start,
                end=end,
                status=Booking.Status.COMPLETED,
                price=offering.price,
                paid=True,
            )
            Booking.objects.filter(pk=session.pk).update(created_at=start - timedelta(days=random.randint(1, 10)))
            session.resources.set(assigned)
            for r in assigned:
                busy.take(r, start, end)
            capacity = offering.capacity or 1
            fill = max(1, round(random.randint(max(1, capacity * 4 // 10), capacity) * self.fill))
            for customer in random.sample(regulars, min(fill, len(regulars))):
                Attendance.objects.create(booking=session, customer=customer)
                seats += 1
                if offering.price > 0 and not self._on_plan(customer, day):
                    self._charge(
                        customer,
                        location,
                        bookingId=str(session.id),
                        description=f"Drop-in · {offering.name} {day.isoformat()}",
                        source="dropin",
                        amount=wire(offering.price),
                        date=day.isoformat(),
                        paid=True,
                    )
            made += 1
        return made, seats

    def _on_plan(self, customer: Customer, day: date) -> bool:
        return Subscription.objects.filter(customer=customer, status="active", started__lte=day).exists()

    def _singles(
        self,
        day: date,
        location: str,
        singles: list[Offering],
        here: list[Resource],
        regulars: list[Customer],
        busy: Busy,
        per_day: int,
    ) -> int:
        if not singles:
            return 0
        # Quieter on Sundays, busier on Saturdays.
        scale = {6: 0.5, 5: 1.3}.get(day.weekday(), 1.0)
        made = 0
        for _ in range(max(1, round(random.gauss(per_day, per_day / 4) * scale))):
            offering = random.choice(singles)
            start, end, units = self._window(day, offering)
            if start is None or end > self.now:
                continue
            assigned = _pick(here, offering, busy, start, end)
            if assigned is None:
                continue
            outcome = random.choices([k for k, _ in OUTCOMES], [w for _, w in OUTCOMES])[0]
            if end > self.now - timedelta(hours=1) and outcome == "completed" and random.random() < 0.3:
                outcome = "checked_in"
            price = (offering.price * units).quantize(Decimal("0.01"))
            paid = outcome == "completed" and random.random() < 0.9
            customer = random.choice(regulars)
            booking = Booking.objects.create(
                tenant_id=self.tenant,
                location_id=location,
                offering=offering,
                customer=customer,
                start=start,
                end=end,
                status=outcome,
                price=price,
                paid=paid,
            )
            Booking.objects.filter(pk=booking.pk).update(created_at=start - timedelta(days=random.randint(0, 12)))
            if outcome != "cancelled":
                booking.resources.set(assigned)
                for r in assigned:
                    busy.take(r, start, end)
            if outcome == "completed" and price > 0:
                self._charge(
                    customer,
                    location,
                    bookingId=str(booking.id),
                    description=f"{offering.name} · {day.isoformat()}",
                    source="booking",
                    amount=wire(price),
                    date=day.isoformat(),
                    paid=paid,
                )
            made += 1
        return made

    def _window(self, day: date, offering: Offering) -> tuple[datetime | None, datetime, Decimal]:
        """A start, an end and how many price units it covers, inside opening hours."""
        if offering.unit in {"day", "night", "month"}:
            count = random.randint(1, 3) if offering.unit != "month" else 1
            start = self._at(day, self.open + 60)
            ends = day + (timedelta(days=30) if offering.unit == "month" else timedelta(days=count))
            return start, self._at(ends, self.open + 60), Decimal(count)
        minutes = offering.minutes or 60
        if offering.time == Offering.Time.WINDOW:
            minutes = random.choice([60, 60, 120, 120, 180, 240])
        latest = self.close - minutes
        if latest < self.open:
            return None, self.now, Decimal(0)
        minute = random.randrange(self.open, latest + 1, SLOT) if latest > self.open else self.open
        start = self._at(day, minute)
        units = Decimal(minutes) / Decimal(60) if offering.unit == "hour" else Decimal(1)
        return start, start + timedelta(minutes=minutes), units

    def _plan_history(self, today: date) -> None:
        """Plan members joined months ago and paid each month since; the latest month may still be due."""
        for sub in Subscription.objects.filter(tenant_id=self.tenant).select_related("offering", "customer"):
            if sub.offering.unit != "month":
                continue
            months = random.randint(1, 8)
            sub.started = today - timedelta(days=30 * months)
            sub.save(update_fields=["started"])
            for m in range(months, 0, -1):
                on = today - timedelta(days=30 * m)
                self._charge(
                    sub.customer,
                    str(sub.customer.location_id),
                    description=f"{sub.offering.name} · {on:%b %Y}",
                    source="plan",
                    amount=wire(sub.offering.price),
                    date=on.isoformat(),
                    paid=not (m == 1 and random.random() < 0.15),
                )
