"""Parties (docs/PLATFORM.md gap 5): accounts, subjects and subscriptions around a customer.

- An **account** groups customers: a company and its contacts, a household and its
  members. Its type (and typed fields) come from the template's `accountTypes`.
- A **subject** is what the business serves for a customer or an account: a pet, a
  child, a vehicle, a property. Its type and fields come from `subjectTypes`; an
  offering with a `subjectType` books one by name.
- A customer may hold several **subscriptions** (plans). A class seat is covered by a
  current monthly plan first, else by a pack with credits; otherwise it's a drop-in.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.internal import audit

from ..models import Account, Customer, Offering, Subject, Subscription
from . import clock, fields, money

if TYPE_CHECKING:
    from datetime import date

    from common.auth import TenantClaims

    from ..models import Booking
    from ..schemas import AccountIn, SubjectIn

MIN_NAME = 2
PLAN_DAYS = 30
WORK = ("bookings.manage", "analytics.view")


# ------------------------------------------------------------- template --


def account_types(claims: TenantClaims) -> list[dict[str, Any]]:
    return list(claims.template.get("accountTypes") or [])


def subject_types(claims: TenantClaims) -> list[dict[str, Any]]:
    return list(claims.template.get("subjectTypes") or [])


def _kind(options: list[dict[str, Any]], key: str, what: str, claims: TenantClaims) -> dict[str, Any]:
    found = next((t for t in options if t.get("key") == key), None)
    if not found:
        msg = (
            _("%(business)s businesses have no account type '%(type)s'")
            if what == "account"
            else _("%(business)s businesses have no subject type '%(type)s'")
        ) % {"business": claims.template.get("label", _("This")), "type": key}
        raise InvalidError(msg)
    return found


def account_fields(claims: TenantClaims, type_key: str) -> list[dict[str, Any]]:
    """An account's fields: the template's `fields.account`, then its type's own."""
    kind = next((t for t in account_types(claims) if t.get("key") == type_key), {})
    return [*fields.defs(claims, "account"), *(kind.get("fields") or [])]


def subject_fields(claims: TenantClaims, type_key: str) -> list[dict[str, Any]]:
    kind = next((t for t in subject_types(claims) if t.get("key") == type_key), {})
    return list(kind.get("fields") or [])


# --------------------------------------------------------------- shapes --


def account_dict(claims: TenantClaims, a: Account, contacts: list[Customer] | None = None) -> dict[str, Any]:
    kind = next((t for t in account_types(claims) if t.get("key") == a.type), {})
    return {
        "id": str(a.id),
        "type": a.type,
        "typeLabel": kind.get("label", a.type.title()),
        "name": a.name,
        "locationId": str(a.location_id),
        "locationName": claims.name_of(str(a.location_id)),
        "fields": fields.visible(claims, account_fields(claims, a.type), a.fields),
        "contacts": [{"id": str(c.id), "name": c.name, "role": c.account_role} for c in contacts or []],
    }


def subject_dict(claims: TenantClaims, s: Subject, today: date) -> dict[str, Any]:
    defs = subject_fields(claims, s.type)
    kind = next((t for t in subject_types(claims) if t.get("key") == s.type), {})
    return {
        "id": str(s.id),
        "type": s.type,
        "typeLabel": kind.get("label", s.type.title()),
        "name": s.name,
        "customerId": str(s.customer_id) if s.customer_id else None,
        "accountId": str(s.account_id) if s.account_id else None,
        "fields": fields.visible(claims, defs, s.fields),
        "expiredFields": fields.expired(defs, s.fields, today),
        "active": s.active,
    }


def subscription_dict(s: Subscription) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "offeringId": str(s.offering_id),
        "name": s.offering.name,
        "unit": s.offering.unit,
        "started": s.started.isoformat(),
        "renews": s.renews.isoformat() if s.renews else None,
        "credits": s.credits,
        "status": s.status,
    }


def subjects_of(customer: Customer) -> list[Subject]:
    """The customer's own subjects and their account's, active only."""
    owners = Q(customer_id=customer.id)
    if customer.account_id:
        owners |= Q(account_id=customer.account_id)
    return list(Subject.objects.filter(owners, tenant_id=customer.tenant_id, active=True))


# -------------------------------------------------------------- accounts --


def accounts(claims: TenantClaims, scope: str | None) -> list[dict[str, Any]]:
    claims.demand_any(WORK)
    rows = list(Account.objects.filter(tenant_id=claims.tenant_id, location_id__in=claims.locations(scope)))
    members: dict[str, list[Customer]] = {}
    for c in Customer.objects.filter(tenant_id=claims.tenant_id, account__in=rows):
        members.setdefault(str(c.account_id), []).append(c)
    return [account_dict(claims, a, members.get(str(a.id))) for a in rows]


def account_of(claims: TenantClaims, account_id: str) -> Account:
    account = Account.objects.filter(tenant_id=claims.tenant_id, id=account_id).first()
    if not account or not claims.reaches(str(account.location_id)):
        msg = _("That account is outside your scope")
        raise NotFoundError(msg)
    return account


@transaction.atomic
def create_account(claims: TenantClaims, body: AccountIn) -> Account:
    claims.demand("bookings.manage")
    claims.require_location(body.location_id)
    _kind(account_types(claims), body.type, "account", claims)
    name = body.name.strip()
    if len(name) < MIN_NAME:
        msg = _("Enter the account's name")
        raise InvalidError(msg)
    account = Account.objects.create(
        tenant_id=claims.tenant_id,
        location_id=body.location_id,
        type=body.type,
        name=name[:160],
        fields=fields.clean(account_fields(claims, body.type), body.fields),
    )
    audit(claims, "account.created", "access", name, body.location_id)
    return account


# -------------------------------------------------------------- subjects --


@transaction.atomic
def create_subject(claims: TenantClaims, body: SubjectIn) -> Subject:
    claims.demand("bookings.manage")
    kind = _kind(subject_types(claims), body.type, "subject", claims)
    if bool(body.customer_id) == bool(body.account_id):
        msg = _("Say whose %(subject)s it is: one customer or one account") % {"subject": kind["label"].lower()}
        raise InvalidError(msg)
    owner: Customer | Account
    if body.customer_id:
        owner = Customer.objects.filter(tenant_id=claims.tenant_id, id=body.customer_id).first()  # type: ignore[assignment]
        if not owner or not claims.reaches(str(owner.location_id)):
            msg = _("That customer is outside your scope")
            raise NotFoundError(msg)
    else:
        owner = account_of(claims, str(body.account_id))
    name = body.name.strip()
    if len(name) < MIN_NAME:
        msg = _("Name the %(subject)s") % {"subject": kind["label"].lower()}
        raise InvalidError(msg)
    subject = Subject.objects.create(
        tenant_id=claims.tenant_id,
        location_id=owner.location_id,
        type=body.type,
        name=name[:160],
        customer=owner if isinstance(owner, Customer) else None,
        account=owner if isinstance(owner, Account) else None,
        fields=fields.clean(subject_fields(claims, body.type), body.fields),
    )
    audit(claims, "subject.created", "access", f"{kind['label']} {name} · {owner.name}", str(owner.location_id))
    return subject


def subject_for(claims: TenantClaims, customer: Customer, subject_id: str | None, type_key: str) -> Subject | None:
    """The subject a booking is for: required (and of the right type) when the offering serves one."""
    if not type_key and not subject_id:
        return None
    label = next((t["label"] for t in subject_types(claims) if t.get("key") == type_key), type_key or _("subject"))
    subject = next((s for s in subjects_of(customer) if str(s.id) == (subject_id or "")), None)
    if not subject or (type_key and subject.type != type_key):
        msg = _("Pick which of %(customer)s's %(subject)ss it is for") % {
            "customer": customer.name,
            "subject": label.lower(),
        }
        raise InvalidError(msg)
    return subject


# --------------------------------------------------------- subscriptions --


def active_subscriptions(customer: Customer, *, lock: bool = False) -> list[Subscription]:
    rows = Subscription.objects.select_related("offering").filter(customer=customer, status=Subscription.Status.ACTIVE)
    return list(rows.select_for_update(of=("self",)) if lock else rows)


@transaction.atomic
def sell(claims: TenantClaims, customer: Customer, offering_id: str) -> Subscription:
    """Add a plan to the customer's subscriptions; selling one they already hold renews or tops it up."""
    claims.demand("payments.collect")
    plan = Offering.objects.filter(
        tenant_id=claims.tenant_id, id=offering_id, time=Offering.Time.NONE, active=True
    ).first()
    if not plan:
        msg = _("Pick an active plan")
        raise InvalidError(msg)
    today = clock.today(claims.zone(str(customer.location_id)))
    held = next((s for s in active_subscriptions(customer, lock=True) if s.offering_id == plan.id), None)
    if held and plan.unit == "month":
        held.renews = max(today, held.renews or today) + timedelta(days=PLAN_DAYS)
        held.save(update_fields=["renews"])
        sub, verb = held, "renewed"
    elif held and plan.unit == "pack":
        held.credits = (held.credits or 0) + (plan.credits or 0)
        held.save(update_fields=["credits"])
        sub, verb = held, "topped up"
    else:
        sub = Subscription.objects.create(
            tenant_id=claims.tenant_id,
            customer=customer,
            offering=plan,
            started=today,
            renews=today + timedelta(days=PLAN_DAYS) if plan.unit == "month" else None,
            credits=plan.credits if plan.unit == "pack" else None,
        )
        verb = "sold"
    money.raise_charge(
        claims,
        customer,
        location_id=str(customer.location_id),
        description=plan.name,
        source="plan",
        amount=plan.price,
        on=today,
        paid=True,
    )
    audit(
        claims, f"plan.{verb.replace(' ', '_')}", "billing", f"{plan.name} → {customer.name}", str(customer.location_id)
    )
    return sub


@transaction.atomic
def cancel(claims: TenantClaims, customer: Customer, subscription_id: str) -> Subscription:
    claims.demand("payments.collect")
    sub = next((s for s in active_subscriptions(customer, lock=True) if str(s.id) == subscription_id), None)
    if not sub:
        msg = _("That plan isn't active")
        raise NotFoundError(msg)
    sub.status = Subscription.Status.CANCELLED
    sub.save(update_fields=["status"])
    audit(claims, "plan.cancelled", "billing", f"{sub.offering.name} · {customer.name}", str(customer.location_id))
    return sub


def cover(customer: Customer, day: date) -> tuple[bool, Subscription | None]:
    """How a class seat on `day` is paid: (covered by a plan, the pack it spent a credit from).

    A current monthly plan covers it outright; otherwise the oldest pack with credits
    spends one. Holding only empty packs is refused, as before; a lapsed monthly plan
    pays as a drop-in (nothing renews plans yet).
    """
    subs = active_subscriptions(customer, lock=True)
    if any(s.offering.unit == "month" and s.renews and s.renews >= day for s in subs):
        return True, None
    packs = [s for s in subs if s.offering.unit == "pack"]
    if not packs:
        return False, None
    pack = next((s for s in packs if s.credits), None)
    if not pack:
        msg = _("%(customer)s's pack has no credits left") % {"customer": customer.name}
        raise InvalidError(msg)
    pack.credits = (pack.credits or 0) - 1
    pack.save(update_fields=["credits"])
    return True, pack


def return_credits(booking: Booking) -> None:
    """A session called off gives every seat paid from a pack its credit back.

    In SQL, not read-modify-write, so a concurrent join can't lose the credit.
    """
    spent = booking.attendances.exclude(subscription=None).values("subscription_id")
    Subscription.objects.filter(id__in=spent).update(credits=Coalesce(F("credits"), 0) + 1)
