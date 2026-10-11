"""Operate: Today, Calendar, Bookings, Customers (with accounts, subjects, plans, documents), Insights."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ninja import Router

from common.auth import TenantAuth, claims_of
from common.schemas import Ok

from ..schemas import AccountIn, BookingIn, CustomerIn, DocumentIn, JoinIn, PlanIn, SessionIn, StatusIn, SubjectIn
from ..services import boards, bookings, customers, parties, shape

if TYPE_CHECKING:
    from django.http import HttpRequest

router = Router(tags=["operate"], auth=TenantAuth())


@router.get("/today")
def today(request: HttpRequest, scope: str | None = None) -> dict[str, Any]:
    return boards.today(claims_of(request), scope)


@router.get("/calendar")
def calendar(request: HttpRequest, scope: str | None = None, day: str | None = None) -> dict[str, Any]:
    return boards.calendar(claims_of(request), scope, day)


@router.get("/insights")
def insights(request: HttpRequest, scope: str | None = None, days: int = 28) -> dict[str, Any]:
    return boards.insights(claims_of(request), scope, days)


@router.get("/bookings")
def list_bookings(request: HttpRequest, scope: str | None = None, range: str = "today") -> dict[str, Any]:  # noqa: A002
    return bookings.list_range(claims_of(request), scope, range)


@router.get("/booking-options")
def booking_options(request: HttpRequest, location: str) -> dict[str, Any]:
    return bookings.options(claims_of(request), location)


@router.get("/availability")
def availability(  # noqa: PLR0913, PLR0917 - one query parameter each
    request: HttpRequest,
    location: str,
    day: str = "",
    offering: str = "",
    staff: str = "",
    resources: str = "",
    minutes: int = 0,
    units: int = 1,
) -> dict[str, Any]:
    picks = [staff, *resources.split(",")]
    return bookings.availability(claims_of(request), location, offering, picks, day, minutes, units)


@router.post("/bookings")
def create_booking(request: HttpRequest, body: BookingIn) -> dict[str, Any]:
    claims = claims_of(request)
    booking = bookings.create(claims, body)
    return {"id": str(booking.id), "status": booking.status}


@router.post("/sessions")
def schedule_session(request: HttpRequest, body: SessionIn) -> dict[str, int]:
    return {"created": len(bookings.schedule_session(claims_of(request), body))}


@router.post("/bookings/{booking_id}/attendees", response=Ok)
def join(request: HttpRequest, booking_id: str, body: JoinIn) -> Ok:
    bookings.join(claims_of(request), booking_id, body.customer_id)
    return Ok()


@router.post("/bookings/{booking_id}/status")
def set_status(request: HttpRequest, booking_id: str, body: StatusIn) -> dict[str, Any]:
    claims = claims_of(request)
    booking = bookings.set_status(claims, booking_id, body.status)
    return shape.booking(claims, shape.with_relations(type(booking).objects.filter(id=booking.id)).get())


@router.get("/customers")
def list_customers(request: HttpRequest, scope: str | None = None) -> list[dict[str, Any]]:
    return customers.read(claims_of(request), scope)


@router.get("/customers/{customer_id}")
def customer_profile(request: HttpRequest, customer_id: str) -> dict[str, Any]:
    return customers.profile(claims_of(request), customer_id)


@router.post("/customers")
def create_customer(request: HttpRequest, body: CustomerIn) -> dict[str, str]:
    return {"id": str(customers.create(claims_of(request), body).id)}


@router.post("/customers/{customer_id}/plan", response=Ok)
def sell_plan(request: HttpRequest, customer_id: str, body: PlanIn) -> Ok:
    customers.sell_plan(claims_of(request), customer_id, body.offering_id)
    return Ok()


@router.post("/customers/{customer_id}/subscriptions/{subscription_id}/cancel", response=Ok)
def cancel_plan(request: HttpRequest, customer_id: str, subscription_id: str) -> Ok:
    customers.cancel_plan(claims_of(request), customer_id, subscription_id)
    return Ok()


@router.post("/customers/{customer_id}/documents", response=Ok)
def record_document(request: HttpRequest, customer_id: str, body: DocumentIn) -> Ok:
    customers.record_document(claims_of(request), customer_id, body)
    return Ok()


@router.get("/accounts")
def list_accounts(request: HttpRequest, scope: str | None = None) -> list[dict[str, Any]]:
    return parties.accounts(claims_of(request), scope)


@router.post("/accounts")
def create_account(request: HttpRequest, body: AccountIn) -> dict[str, str]:
    return {"id": str(parties.create_account(claims_of(request), body).id)}


@router.post("/subjects")
def create_subject(request: HttpRequest, body: SubjectIn) -> dict[str, str]:
    return {"id": str(parties.create_subject(claims_of(request), body).id)}
