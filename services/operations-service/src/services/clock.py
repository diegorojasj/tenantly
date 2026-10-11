"""Time: stored as aware UTC, read and written in the location's own wall clock.

On the wire a booking time is the location's wall clock, `YYYY-MM-DDTHH:MM`, and a
day is `YYYY-MM-DD` in that location's calendar. Each location names its IANA
zone in the tenant token (default UTC, so a business that never sets one sees
exactly the old behaviour). Opening hours are minutes from local midnight.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from common.auth import UTC_ZONE
from common.errors import InvalidError

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from common.auth import TenantClaims

DAY = 24 * 60


def now() -> datetime:
    return timezone.now()


def today(tz: tzinfo = UTC) -> date:
    return now().astimezone(tz).date()


def stamp(value: datetime, tz: tzinfo = UTC) -> str:
    return value.astimezone(tz).strftime("%Y-%m-%dT%H:%M")


def parse_stamp(value: str, tz: tzinfo = UTC) -> datetime:
    """A local wall-clock stamp -> aware UTC."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")  # noqa: DTZ007 - the zone is attached below
    except ValueError as exc:
        msg = _("Pick a start time")
        raise InvalidError(msg) from exc
    return parsed.replace(tzinfo=tz).astimezone(UTC)


def parse_day(value: str | None, tz: tzinfo = UTC) -> date:
    if not value:
        return today(tz)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        msg = _("Pick a valid day")
        raise InvalidError(msg) from exc


def at(day: date, minute: int, tz: tzinfo = UTC) -> datetime:
    """`minute` past local midnight on `day`, as aware UTC (wall-clock, so DST days still line up)."""
    local = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(minutes=minute)
    return local.astimezone(UTC)


def local(value: datetime, tz: tzinfo) -> datetime:
    return value.astimezone(tz)


def minute_of(value: datetime, tz: tzinfo = UTC) -> int:
    wall = value.astimezone(tz)
    return wall.hour * 60 + wall.minute


def clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def add_months(value: datetime, months: int) -> datetime:
    """Same wall-clock time `months` later, clamped to the month's last day (Jan 31 + 1 -> Feb 28)."""
    month = value.month - 1 + months
    year, month = value.year + month // 12, month % 12 + 1
    following = date(year + month // 12, month % 12 + 1, 1)
    return value.replace(year=year, month=month, day=min(value.day, (following - timedelta(days=1)).day))


# -------------------------------------------------------- many locations --


def zone_of(claims: TenantClaims, locations: set[str]) -> ZoneInfo:
    """One zone for a page covering several locations: theirs if they share one, else UTC."""
    zones = {claims.zone(loc).key for loc in locations}
    return claims.zone(next(iter(locations))) if len(zones) == 1 else UTC_ZONE


def within_days(claims: TenantClaims, locations: set[str], first: date, last: date, *, overlap: bool = False) -> Q:
    """Bookings on local days `first`..`last`, each location by its own calendar.

    By default a booking belongs to the day it starts; with `overlap`, to every
    day it covers (a three-night stay shows on each of its days).
    """
    by_zone: dict[str, list[str]] = {}
    for loc in locations:
        by_zone.setdefault(claims.zone(loc).key, []).append(loc)
    match = Q(pk__in=[])
    for ids in by_zone.values():
        tz = claims.zone(ids[0])
        begin, end = at(first, 0, tz), at(last + timedelta(days=1), 0, tz)
        span = Q(start__lt=end, end__gt=begin) if overlap else Q(start__gte=begin, start__lt=end)
        match |= Q(location_id__in=ids) & span
    return match
