"""Bookings: availability, booking, class sessions, and the lifecycle.

Every write locks the resources it touches before checking for clashes, so two
desks booking the same coach at the same moment can't both succeed. Nothing is
booked into a downtime (services/downtimes.py) of the location, the offering, or
any resource it needs. Money follows the lifecycle through the billing service,
and the policies decide how.
"""

from __future__ import annotations

from datetime import UTC, date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Q
from django.utils import dateformat
from django.utils.translation import gettext as _

from common.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError
from common.internal import audit

from ..models import Attendance, Booking, Customer, Offering, Resource, Subject
from . import clock, documents, downtimes, fields, fulfilment, money, parties, policies, shape, usage

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime, tzinfo

    from common.auth import TenantClaims

    from ..schemas import BookingIn, SessionIn

WORK = ("bookings.manage", "analytics.view")
SLOT_STEP = 30
MAX_RENTAL_MINUTES = 8 * 60  # hourly rentals; day / night / month offerings span days instead
# Units an offering is priced and booked in whole days of: the most of each one booking may take.
MAX_UNITS = {"day": 31, "night": 31, "month": 12}
MAX_REPEAT_WEEKS = 12
LIST_DAYS = 7

FEE_SHARE = {
    "None": Decimal(0),
    "25% of price": Decimal("0.25"),
    "50% of price": Decimal("0.5"),
    "Full price": Decimal(1),
}


# --------------------------------------------------------------- helpers --


def _single(o: Offering) -> bool:
    """Booked one customer per slot (an appointment, a rental, a visit…)."""
    return o.time != Offering.Time.NONE and not o.shared


def _session(o: Offering) -> bool:
    """Scheduled as a session customers join (a class, a tour…)."""
    return o.time == Offering.Time.SLOT and o.shared


def _length(offering: Offering, minutes: int | None) -> int:
    if offering.time == Offering.Time.WINDOW:
        return max(60, min(minutes or offering.minutes, MAX_RENTAL_MINUTES))
    return offering.minutes


def _end(offering: Offering, start: datetime, tz: tzinfo, minutes: int | None, units: int | None) -> datetime:
    """When a booking starting at `start` ends: minutes for hours and sessions, whole local days otherwise."""
    if offering.unit not in MAX_UNITS:
        return start + timedelta(minutes=_length(offering, minutes))
    count = max(1, min(units or 1, MAX_UNITS[offering.unit]))
    wall = clock.local(start, tz)
    later = clock.add_months(wall, count) if offering.unit == "month" else wall + timedelta(days=count)
    return later.astimezone(UTC)


def _wall_minutes(start: datetime, end: datetime, tz: tzinfo) -> int:
    """Length on the location's wall clock, so a DST change never adds or drops a priced day."""
    a, b = clock.local(start, tz).replace(tzinfo=None), clock.local(end, tz).replace(tzinfo=None)
    return int((b - a).total_seconds() // 60)


def _covered(offering: Offering, start: datetime, end: datetime, tz: tzinfo) -> Decimal:
    """How many of the offering's price units the booking covers; partial days and months round up."""
    wall_start, wall_end = clock.local(start, tz), clock.local(end, tz)
    minutes = Decimal(_wall_minutes(start, end, tz))
    if offering.unit == "hour":
        return Decimal(int((end - start).total_seconds()) // 60) / Decimal(60)
    if offering.unit == "day":
        return max(Decimal(1), (minutes / Decimal(clock.DAY)).to_integral_value(rounding=ROUND_CEILING))
    if offering.unit == "night":
        return Decimal(max(1, (wall_end.date() - wall_start.date()).days))
    if offering.unit == "month":
        months = 1
        while clock.add_months(wall_start, months) < wall_end:
            months += 1
        return Decimal(months)
    return Decimal(1)


def _price(offering: Offering, start: datetime, end: datetime, tz: tzinfo) -> Decimal:
    return (offering.price * _covered(offering, start, end, tz)).quantize(Decimal("0.01"))


def _window_check(claims: TenantClaims, location_id: str, day: date) -> None:
    today = clock.today(claims.zone(location_id))
    if day < today:
        msg = _("That day has already passed")
        raise InvalidError(msg)
    window = int(policies.effective(claims, location_id, "booking.window"))
    if day > today + timedelta(days=window):
        msg = _("%(location)s takes bookings up to %(n)s days ahead") % {
            "location": claims.name_of(location_id),
            "n": window,
        }
        raise InvalidError(msg)


def _fits(claims: TenantClaims, location_id: str, start: datetime, end: datetime) -> bool:
    """Inside the location's opening hours, on its own wall clock.

    A booking that ends the day it starts must fit between opening and closing;
    one that spans days must start and end (pick-up and return) while it's open.
    """
    tz = claims.zone(location_id)
    opens, closes = claims.hours(location_id)
    begin = clock.minute_of(start, tz)
    finish = begin + _wall_minutes(start, end, tz)
    if finish <= clock.DAY:
        return opens <= begin and finish <= closes
    back = clock.minute_of(end, tz) or clock.DAY
    return opens <= begin < closes and opens <= back <= closes


def _hours_check(claims: TenantClaims, location_id: str, start: datetime, end: datetime) -> None:
    if not _fits(claims, location_id, start, end):
        opens, closes = claims.hours(location_id)
        msg = _("Must fit inside opening hours (%(opens)s to %(closes)s)") % {
            "opens": clock.clock(opens),
            "closes": clock.clock(closes),
        }
        raise InvalidError(msg)
    if start < clock.now():
        msg = _("That time has already passed")
        raise InvalidError(msg)


def _offering(claims: TenantClaims, offering_id: str, rule: Callable[[Offering], bool]) -> Offering:
    offering = Offering.objects.filter(tenant_id=claims.tenant_id, id=offering_id, active=True).first()
    if not offering or not rule(offering):
        msg = _("Pick something that can be booked")
        raise InvalidError(msg)
    return offering


def _customer(claims: TenantClaims, customer_id: str) -> Customer:
    customer = Customer.objects.prefetch_related("documents").filter(tenant_id=claims.tenant_id, id=customer_id)
    found = customer.select_for_update(of=("self",)).first()
    # Same scope rule as the Customers page: a desk only books the people it can see.
    if not found or not claims.reaches(str(found.location_id)):
        msg = _("Pick a %(customer)s") % {"customer": claims.template["terms"]["customer"].lower()}
        raise InvalidError(msg)
    return found


def _get(claims: TenantClaims, booking_id: str) -> Booking:
    booking = (
        Booking.objects.select_for_update(of=("self",))
        .select_related("offering", "customer")
        .filter(tenant_id=claims.tenant_id, id=booking_id)
        .first()
    )
    if not booking or not claims.reaches(str(booking.location_id)):
        msg = _("That booking is outside your scope")
        raise NotFoundError(msg)
    return booking


# --------------------------------------------------------------- reading --


def options(claims: TenantClaims, location_id: str) -> dict[str, Any]:
    claims.require_location(location_id)
    now = clock.now()
    sessions = shape.with_relations(
        Booking.objects.filter(
            tenant_id=claims.tenant_id,
            location_id=location_id,
            customer__isnull=True,
            status=Booking.Status.CONFIRMED,
            start__gt=now,
            start__lt=now + timedelta(days=LIST_DAYS),
        )
    )
    active = Offering.objects.filter(tenant_id=claims.tenant_id, active=True)
    opens, closes = claims.hours(location_id)
    customer_fields = fields.defs(claims, "customer")
    customers = list(Customer.objects.filter(tenant_id=claims.tenant_id, location_id=location_id))
    subjects: dict[Any, list[Subject]] = {}
    owned = Subject.objects.filter(tenant_id=claims.tenant_id, active=True).filter(
        Q(customer__in=customers) | Q(account__in={c.account_id for c in customers if c.account_id})
    )
    by_account: dict[Any, list[Subject]] = {}
    for x in owned:
        if x.customer_id:
            subjects.setdefault(x.customer_id, []).append(x)
        else:
            by_account.setdefault(x.account_id, []).append(x)
    for c in customers:
        if c.account_id:
            subjects.setdefault(c.id, []).extend(by_account.get(c.account_id, []))
    return {
        "locationId": location_id,
        "tz": claims.zone(location_id).key,
        "hours": [opens, closes],
        "approval": policies.effective(claims, location_id, "booking.approval") is True,
        "offerings": [shape.offering(o) for o in active if _single(o)],
        "classes": [shape.offering(o) for o in active if _session(o)],
        # Everything in service here; the form offers each `pick` requirement the ones that match it.
        "resources": [
            shape.resource(r)
            for r in Resource.objects.filter(
                tenant_id=claims.tenant_id, location_id=location_id, status="available"
            ).order_by("name")
        ],
        "customers": [
            {
                "id": str(c.id),
                "name": c.name,
                "detail": fields.summary(claims, customer_fields, c.fields),
                # What the business serves for them (theirs and their account's), for offerings that need one.
                "subjects": [{"id": str(x.id), "type": x.type, "name": x.name} for x in subjects.get(c.id, [])],
            }
            for c in customers
        ],
        "subjectTypes": parties.subject_types(claims),
        "bookingFields": fields.defs(claims, "booking"),
        "sessions": [shape.booking(claims, b) for b in sessions],
    }


def availability(
    claims: TenantClaims,
    location_id: str,
    offering_id: str,
    picks: list[str],
    day_value: str,
    minutes: int,
    units: int = 1,
) -> dict[str, Any]:
    """The same checks `create` runs, so the form only offers times that will be accepted."""
    claims.require_location(location_id)
    offering = Offering.objects.filter(tenant_id=claims.tenant_id, id=offering_id, active=True).first()
    if not offering or not _single(offering):
        return {"slots": [], "reason": _("Pick what to book first.")}
    tz = claims.zone(location_id)
    day = clock.parse_day(day_value, tz)
    try:
        _window_check(claims, location_id, day)
    except InvalidError as exc:
        return {"slots": [], "reason": exc.detail + "."}
    try:
        needs = fulfilment.needs(claims, offering.requires, location_id, picks)
    except InvalidError as exc:
        return {"slots": [], "reason": exc.detail + "."}
    opens, closes = claims.hours(location_id)
    now = clock.now()
    # The location's and the offering's downtimes, read once for the day (and a span's last end).
    closed = downtimes.windows(
        claims,
        location_id,
        offering,
        clock.at(day, opens, tz),
        _end(offering, clock.at(day, closes, tz), tz, minutes, units),
    )
    slots = []
    for minute in range(opens, closes, SLOT_STEP):
        start = clock.at(day, minute, tz)
        end = _end(offering, start, tz, minutes, units)
        if start < now or not _fits(claims, location_id, start, end) or downtimes.closing(closed, start, end):
            continue
        if not fulfilment.free(needs, start, end):
            continue
        slots.append(clock.clock(minute))
    reason = ""
    if not slots and closed:
        reason = _("Unavailable that day: %(what)s.") % {
            "what": ", ".join(downtimes.describe(claims, d) for d in closed[:2])
        }
    elif not slots:
        chosen = [r.name for n in needs for r in n.picked]
        reason = (
            _("Nothing free that day for %(names)s. Try another day or person.") % {"names": ", ".join(chosen)}
            if chosen
            else _("Nothing free that day. Try another day.")
        )
    return {"slots": slots, "reason": reason}


def list_range(claims: TenantClaims, scope: str | None, range_: str) -> dict[str, Any]:
    claims.demand_any(WORK)
    locations = claims.locations(scope)
    today = clock.today(clock.zone_of(claims, locations))
    first, last = {
        "upcoming": (today + timedelta(days=1), today + timedelta(days=LIST_DAYS)),
        "past": (today - timedelta(days=LIST_DAYS), today - timedelta(days=1)),
    }.get(range_, (today, today))
    rows = shape.with_relations(
        Booking.objects.filter(clock.within_days(claims, locations, first, last), tenant_id=claims.tenant_id)
    ).order_by("-start" if range_ == "past" else "start")
    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "canManage": claims.can("bookings.manage"),
        "bookings": shape.bookings(claims, rows),
    }


# --------------------------------------------------------------- writing --


@transaction.atomic
def create(claims: TenantClaims, body: BookingIn) -> Booking:
    """One customer, one slot: an appointment, a rental, a visit — any offering for one customer at a time."""
    claims.demand("bookings.manage")
    claims.allow("bookings.add")
    claims.require_location(body.location_id)
    offering = _offering(claims, body.offering_id, _single)
    customer = _customer(claims, body.customer_id)
    subject = parties.subject_for(claims, customer, body.subject_id, offering.subject_type)
    values = fields.clean(fields.defs(claims, "booking"), body.fields)
    tz = claims.zone(body.location_id)
    start = clock.parse_stamp(body.start, tz)
    end = _end(offering, start, tz, body.minutes, body.units)
    day = clock.local(start, tz).date()
    _window_check(claims, body.location_id, day)
    _hours_check(claims, body.location_id, start, end)
    downtimes.demand_open(claims, body.location_id, offering, start, end)
    documents.demand(claims, customer, day, body.location_id, subject)

    # Picked resources must be free; the rest are interchangeable, so the first free ones are taken.
    picks = [body.staff_id or "", *body.resource_ids]
    assigned = fulfilment.take(
        fulfilment.needs(claims, offering.requires, body.location_id, picks, lock=True), start, end
    )

    approval = policies.effective(claims, body.location_id, "booking.approval") is True
    booking = Booking.objects.create(
        tenant_id=claims.tenant_id,
        location_id=body.location_id,
        offering=offering,
        customer=customer,
        subject=subject,
        fields=values,
        start=start,
        end=end,
        status=Booking.Status.REQUESTED if approval else Booking.Status.CONFIRMED,
        price=_price(offering, start, end, tz),
    )
    booking.resources.set(assigned)
    until = f" → {clock.stamp(end, tz).replace('T', ' ')}" if offering.unit in MAX_UNITS else ""
    who = f"{customer.name} · {subject.name}" if subject else customer.name
    audit(
        claims,
        "booking.created",
        "config",
        f"{offering.name} · {who} · {body.start.replace('T', ' ')}{until}",
        body.location_id,
    )
    return booking


@transaction.atomic
def schedule_session(claims: TenantClaims, body: SessionIn) -> list[Booking]:
    """Put a class or tour on the calendar, optionally repeating weekly."""
    claims.demand("bookings.manage")
    claims.allow("bookings.add")
    claims.require_location(body.location_id)
    offering = _offering(claims, body.offering_id, _session)
    picks = [body.staff_id or "", *body.resource_ids]
    needs = fulfilment.needs(claims, offering.requires, body.location_id, picks, lock=True)
    tz = claims.zone(body.location_id)
    first = clock.local(clock.parse_stamp(body.start, tz), tz)
    weeks = max(1, min(body.repeat_weeks, MAX_REPEAT_WEEKS))
    created: list[Booking] = []
    for week in range(weeks):
        wall = first + timedelta(weeks=week)  # same local time each week, across DST changes
        start = wall.astimezone(UTC)
        end = start + timedelta(minutes=offering.minutes)
        if week == 0:
            _window_check(claims, body.location_id, wall.date())
        _hours_check(claims, body.location_id, start, end)
        downtimes.demand_open(claims, body.location_id, offering, start, end)
        when = _("on %(day)s at %(time)s") % {"day": dateformat.format(wall, "D d M"), "time": f"{wall:%H:%M}"}
        assigned = fulfilment.take(needs, start, end, when)
        session = Booking.objects.create(
            tenant_id=claims.tenant_id,
            location_id=body.location_id,
            offering=offering,
            start=start,
            end=end,
            status=Booking.Status.CONFIRMED,
            price=offering.price,
            paid=True,
        )
        session.resources.set(assigned)
        created.append(session)
    repeat = f", weekly for {weeks} weeks" if weeks > 1 else ""
    audit(
        claims,
        "session.scheduled",
        "config",
        f"{offering.name} · {body.start.replace('T', ' ')}{repeat}",
        body.location_id,
    )
    return created


@transaction.atomic
def join(claims: TenantClaims, booking_id: str, customer_id: str) -> Booking:
    claims.demand("bookings.manage")
    claims.allow("bookings.add")
    session = _get(claims, booking_id)
    if session.customer_id or not session.offering.shared:
        msg = _("That isn't a class session")
        raise InvalidError(msg)
    if session.status != Booking.Status.CONFIRMED or session.start < clock.now():
        msg = _("That session is no longer open")
        raise InvalidError(msg)
    downtimes.refuse_seat(claims, session)
    customer = _customer(claims, customer_id)
    tz = claims.zone(str(session.location_id))
    day = clock.local(session.start, tz).date()
    if session.attendances.filter(customer=customer).exists():
        msg = _("%(customer)s is already booked") % {"customer": customer.name}
        raise ConflictError(msg)
    if session.attendances.count() >= (session.offering.capacity or 0):
        msg = _("%(offering)s is full") % {"offering": session.offering.name}
        raise ConflictError(msg)
    documents.demand(claims, customer, day, str(session.location_id))
    covered, pack = parties.cover(customer, day)
    if not covered and session.price > 0:
        # No plan: a paid drop-in, tied to the session so a cancellation refunds it.
        money.raise_charge(
            claims,
            customer,
            location_id=str(session.location_id),
            description=f"Drop-in · {session.offering.name} {clock.stamp(session.start, tz)}",
            source="dropin",
            amount=session.price,
            on=day,
            paid=True,
            booking_id=str(session.id),
        )
    seat = Attendance.objects.create(booking=session, customer=customer, subscription=pack)
    usage.served(claims, customer, "attendance", f"attendance:{seat.id}")
    audit(
        claims,
        "booking.joined",
        "config",
        f"{customer.name} → {session.offering.name} {clock.stamp(session.start, tz)}",
        str(session.location_id),
    )
    return session


def _fee(claims: TenantClaims, booking: Booking, reason: str) -> None:
    share = FEE_SHARE.get(str(policies.effective(claims, str(booking.location_id), "payments.noShowFee")), Decimal(0))
    if booking.customer and share > 0 and booking.price > 0:
        money.raise_charge(
            claims,
            booking.customer,
            location_id=str(booking.location_id),
            description=f"{reason} · {booking.offering.name}",
            source="fee",
            amount=(booking.price * share).quantize(Decimal("0.01")),
            on=clock.today(claims.zone(str(booking.location_id))),
            paid=False,
            booking_id=str(booking.id),
        )


def _usage(claims: TenantClaims, booking: Booking, status: str) -> None:
    """Served (counts the customer on Tenantly's bill), handled, or a class called off."""
    if status in {"checked_in", "completed"} and booking.customer:
        usage.served(claims, booking.customer, f"booking.{status}", f"booking:{booking.id}")
    if status == "completed":
        usage.completed(claims, booking)
    if status == "cancelled" and not booking.customer_id:
        for seat in booking.attendances.select_related("customer"):
            usage.unserved(claims, seat.customer, f"attendance:{seat.id}")


@transaction.atomic
def set_status(claims: TenantClaims, booking_id: str, status: str) -> Booking:
    claims.demand("bookings.manage")
    booking = _get(claims, booking_id)
    labels = claims.template["status"]
    if status not in claims.moves(booking.status):
        msg = _("A %(current)s booking can't become %(next)s") % {
            "current": labels[booking.status].lower(),
            "next": labels.get(status, status).lower(),
        }
        raise InvalidError(msg)
    now = clock.now()
    tz = claims.zone(str(booking.location_id))
    if status == "no_show":
        grace = int(policies.effective(claims, str(booking.location_id), "booking.grace"))
        if now < booking.start + timedelta(minutes=grace):
            msg = _("Wait until %(n)s minutes after the start before marking a no-show") % {"n": grace}
            raise ForbiddenError(msg)
        _fee(claims, booking, "No-show fee")
    if status == "completed" and booking.customer and booking.price > 0:
        money.raise_charge(
            claims,
            booking.customer,
            location_id=str(booking.location_id),
            description=f"{booking.offering.name} · {clock.local(booking.start, tz):%Y-%m-%d}",
            source="booking",
            amount=booking.price,
            on=clock.local(now, tz).date(),
            paid=booking.paid,
            booking_id=str(booking.id),
        )
    if status == "cancelled":
        money.refund_booking(claims, str(booking.id))
        hours = int(policies.effective(claims, str(booking.location_id), "booking.cancelHours"))
        # Called off because of a downtime is the business's doing: no late fee.
        late = booking.start - now < timedelta(hours=hours)
        if booking.customer and late and not downtimes.covering(claims, booking):
            _fee(claims, booking, "Late cancellation fee")
        # Seats paid from a pack get their credit back when a class is called off.
        parties.return_credits(booking)
    _usage(claims, booking, status)
    booking.status = status
    booking.save(update_fields=["status"])
    who = booking.customer.name if booking.customer else booking.offering.name
    audit(
        claims,
        f"booking.{status}",
        "config",
        f"{who} · {booking.offering.name} · {clock.stamp(booking.start, tz)}",
        str(booking.location_id),
    )
    return booking
