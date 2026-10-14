"""Request bodies. Responses are plain dicts shaped for the frontend's types (see services/shape.py)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from common.schemas import CamelSchema


class RequirementIn(CamelSchema):
    """One line of an offering's requirement list: `quantity` resources of `type` (services/fulfilment.py)."""

    type: str = Field(max_length=30)
    quantity: int = Field(default=1, ge=0, le=20)
    # The desk chooses which ones; unset follows the type (team members are picked, things assigned).
    pick: bool | None = None
    role: str | None = Field(default=None, max_length=60)
    where: dict[str, Any] | None = None


class OfferingIn(CamelSchema):
    # The template preset it starts from; every rule below defaults to the preset's.
    kind: str = Field(max_length=20)
    name: str
    category: str = ""
    minutes: int = Field(default=60, ge=0, le=24 * 60)
    # A decimal string ("12.50") or a number; never rounded through a float.
    price: Decimal = Field(ge=0, le=100_000, max_digits=10, decimal_places=2)
    capacity: int | None = Field(default=None, ge=0, le=1000)
    credits: int | None = Field(default=None, ge=0, le=1000)
    # What the price buys (one of the preset's units): session; hour / day / night / month; month / pack.
    unit: Literal["session", "hour", "day", "night", "month", "pack"] | None = None
    place: Literal["on_site", "at_customer"] | None = None
    requires: list[RequirementIn] | None = None
    # The subject type each booking must name (a pet, a vehicle); defaults to the preset's.
    subject_type: str | None = Field(default=None, max_length=30)
    fields: dict[str, Any] | None = None


class ResourceIn(CamelSchema):
    location_id: str
    # One of the template's resource type keys.
    type: str = Field(max_length=30)
    name: str
    role: str
    attributes: dict[str, Any] | None = None
    parent_id: str | None = None


class ResourceStatusIn(CamelSchema):
    status: Literal["available", "out_of_service"]


class DowntimeIn(CamelSchema):
    """A resource, an offering at a location, or (with neither) the whole location taken out of use."""

    location_id: str | None = None
    resource_id: str | None = None
    offering_id: str | None = None
    reason: Literal["maintenance", "repair", "unfit", "absence", "closure", "other"]
    note: str = Field(default="", max_length=300)
    # Wall-clock stamps at the location ("2026-10-14T09:00"); no start means now, no end until it's ended.
    start: str | None = None
    end: str | None = None


class DowntimeMoneyIn(CamelSchema):
    kind: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, lt=100_000_000, max_digits=10, decimal_places=2)
    description: str = Field(default="", max_length=200)
    # Free text for the ledger (Parts, Labour, Insurance…); defaults to the downtime's reason.
    category: str = Field(default="", max_length=40)
    # Income only: charge it to this customer (damage they caused) instead of recording it as other income.
    customer_id: str | None = None
    # The day it was paid or earned; today at the location by default.
    on: date | None = None


class CustomerIn(CamelSchema):
    location_id: str
    name: str
    phone: str = ""
    email: str = ""
    fields: dict[str, Any] | None = None
    # An existing account to join, or a new one to open (type + name), and the role in it.
    account_id: str | None = None
    account_type: str | None = Field(default=None, max_length=30)
    account_name: str | None = Field(default=None, max_length=160)
    account_role: str = Field(default="", max_length=60)


class AccountIn(CamelSchema):
    location_id: str
    # One of the template's account type keys (business, household…).
    type: str = Field(max_length=30)
    name: str
    fields: dict[str, Any] | None = None


class SubjectIn(CamelSchema):
    # One of the template's subject type keys (pet, vehicle, property…).
    type: str = Field(max_length=30)
    name: str
    customer_id: str | None = None
    account_id: str | None = None
    fields: dict[str, Any] | None = None


class DocumentIn(CamelSchema):
    # One of the template's document type keys.
    type: str = Field(max_length=30)
    subject_id: str | None = None
    issued: str | None = None
    # Defaults to the type's `validDays` after `issued`; none means it never expires.
    expires: str | None = None
    reference: str = Field(default="", max_length=120)


class PlanIn(CamelSchema):
    offering_id: str


class BookingIn(CamelSchema):
    location_id: str
    offering_id: str
    customer_id: str
    start: str
    minutes: int | None = None
    # Day / night / month offerings: how many of them (the end follows on the location's calendar).
    units: int | None = Field(default=None, ge=1, le=31)
    # The resources the desk picked for the offering's `pick` requirements (staffId is the one-person shorthand).
    staff_id: str | None = None
    resource_ids: list[str] = Field(default_factory=list, max_length=40)
    # What it's for, when the offering serves a subject; and the template's booking fields.
    subject_id: str | None = None
    fields: dict[str, Any] | None = None


class SessionIn(CamelSchema):
    location_id: str
    offering_id: str
    staff_id: str | None = None
    resource_ids: list[str] = Field(default_factory=list, max_length=40)
    start: str
    repeat_weeks: int = Field(default=1, ge=1, le=12)


class JoinIn(CamelSchema):
    customer_id: str


class StatusIn(CamelSchema):
    status: Literal["confirmed", "checked_in", "completed", "no_show", "cancelled"]


class PolicyIn(CamelSchema):
    scope: str
    key: str
    value: bool | int | float | str | None = None
