"""Customers: who the business serves, with the template's typed fields, their account, subjects,
subscriptions and documents (docs/PLATFORM.md gaps 5-6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils.translation import gettext as _

from common.errors import InvalidError, NotFoundError
from common.internal import audit
from common.money import wire

from ..models import Attendance, Booking, Customer, Offering, Subscription
from ..schemas import AccountIn
from . import clock, documents, fields, money, parties, shape

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from common.auth import TenantClaims

    from ..schemas import CustomerIn, DocumentIn

WORK = ("bookings.manage", "analytics.view")
MIN_NAME = 2


def _visits(claims: TenantClaims, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Completed visits per customer: single bookings plus class seats."""
    out: dict[str, dict[str, Any]] = {}

    def bump(cid: str, start: str) -> None:
        entry = out.setdefault(cid, {"visits": 0, "last": None})
        entry["visits"] += 1
        if not entry["last"] or start > entry["last"]:
            entry["last"] = start

    singles = Booking.objects.filter(
        tenant_id=claims.tenant_id, customer_id__in=ids, status=Booking.Status.COMPLETED
    ).values_list("customer_id", "start", "location_id")
    for cid, start, loc in singles:
        bump(str(cid), clock.stamp(start, claims.zone(str(loc))))
    seats = Attendance.objects.filter(
        customer_id__in=ids, booking__status=Booking.Status.COMPLETED, booking__tenant_id=claims.tenant_id
    ).values_list("customer_id", "booking__start", "booking__location_id")
    for cid, start, loc in seats:
        bump(str(cid), clock.stamp(start, claims.zone(str(loc))))
    return out


def _related(rows: QuerySet[Customer]) -> QuerySet[Customer]:
    return rows.select_related("account").prefetch_related(
        "documents", Prefetch("subscriptions", queryset=Subscription.objects.select_related("offering"))
    )


def customer_dict(
    claims: TenantClaims,
    c: Customer,
    visits: dict[str, Any] | None,
    money_row: dict[str, str] | None,
    rules: dict[str, str] | None = None,
) -> dict[str, Any]:
    """`rules` are the document requirements at the customer's location (documents.rules_at)."""
    today = clock.today(claims.zone(str(c.location_id)))
    defs = fields.defs(claims, "customer")
    account = None
    if c.account:
        kind = next((t for t in parties.account_types(claims) if t.get("key") == c.account.type), {})
        label = kind.get("label", c.account.type.title())
        account = {"id": str(c.account_id), "name": c.account.name, "typeLabel": label, "role": c.account_role}
    rules = documents.rules_at(claims, str(c.location_id)) if rules is None else rules
    return {
        "id": str(c.id),
        "locationId": str(c.location_id),
        "locationName": claims.name_of(str(c.location_id)),
        "name": c.name,
        "phone": c.phone,
        "email": c.email,
        "since": c.since.isoformat(),
        "fields": fields.visible(claims, defs, c.fields),
        "expiredFields": fields.expired(defs, c.fields, today),
        "account": account,
        "subscriptions": [
            parties.subscription_dict(s) for s in c.subscriptions.all() if s.status == Subscription.Status.ACTIVE
        ],
        "documents": [documents.doc_dict(claims, d, today) for d in c.documents.all()],
        # Customer documents the policy here asks for with none valid today (subject ones are checked per booking).
        "missingDocuments": [
            {"key": k["key"], "label": k["label"]} for k in documents.missing(claims, c, today, rules)
        ],
        "balance": wire((money_row or {}).get("balance")),
        "visits": (visits or {}).get("visits", 0),
        "spend": wire((money_row or {}).get("spend")),
        "lastVisit": (visits or {}).get("last"),
    }


def read(claims: TenantClaims, scope: str | None) -> list[dict[str, Any]]:
    claims.demand_any(WORK)
    locations = claims.locations(scope)
    rows = list(_related(Customer.objects.filter(tenant_id=claims.tenant_id, location_id__in=locations)))
    ids = [str(c.id) for c in rows]
    visits = _visits(claims, ids)
    balances = money.balances(claims, ids) if ids else {}
    rules = {loc: documents.rules_at(claims, loc) for loc in {str(c.location_id) for c in rows}}
    return [
        customer_dict(claims, c, visits.get(str(c.id)), balances.get(str(c.id)), rules[str(c.location_id)])
        for c in rows
    ]


def _get(claims: TenantClaims, customer_id: str, *, lock: bool = False) -> Customer:
    rows = _related(Customer.objects.filter(tenant_id=claims.tenant_id, id=customer_id))
    customer = (rows.select_for_update(of=("self",)) if lock else rows).first()
    if not customer or not claims.reaches(str(customer.location_id)):
        msg = _("That customer is outside your scope")
        raise NotFoundError(msg)
    return customer


def profile(claims: TenantClaims, customer_id: str) -> dict[str, Any]:
    claims.demand_any(WORK)
    c = _get(claims, customer_id)
    history = shape.with_relations(
        Booking.objects.filter(tenant_id=claims.tenant_id).filter(Q(customer=c) | Q(attendances__customer=c))
    ).distinct()
    cid = str(c.id)
    today = clock.today(claims.zone(str(c.location_id)))
    rules = documents.rules_at(claims, str(c.location_id))
    subjects = parties.subjects_of(c)
    contacts = list(Customer.objects.filter(account_id=c.account_id).exclude(id=c.id)) if c.account_id else []
    return {
        "customer": customer_dict(
            claims, c, _visits(claims, [cid]).get(cid), money.balances(claims, [cid]).get(cid), rules
        ),
        # Every document type, with how much the policy here asks for it.
        "documentTypes": [{**k, "level": rules.get(k["key"], documents.OFF)} for k in documents.types(claims)],
        "subjects": [parties.subject_dict(claims, s, today) for s in subjects],
        # What each subject is missing that the policy asks for (subject documents only).
        "subjectMissing": {
            str(s.id): [
                k["label"]
                for k in documents.missing(claims, c, today, rules, subject=s)
                if k.get("appliesTo") == "subject"
            ]
            for s in subjects
        },
        "contacts": [{"id": str(o.id), "name": o.name, "role": o.account_role} for o in contacts],
        "history": shape.bookings(claims, history.order_by("-start")[:12]),
        "charges": money.customer_charges(claims, cid),
        "plans": [
            shape.offering(o)
            for o in Offering.objects.filter(tenant_id=claims.tenant_id, time=Offering.Time.NONE, active=True)
        ],
        "canBook": claims.can("bookings.manage"),
        "canCollect": claims.can("payments.collect"),
    }


@transaction.atomic
def create(claims: TenantClaims, body: CustomerIn) -> Customer:
    claims.demand("bookings.manage")
    claims.allow("customers.add")
    claims.require_location(body.location_id)
    name = body.name.strip()
    if len(name) < MIN_NAME:
        msg = _("Enter a name")
        raise InvalidError(msg)
    values = fields.clean(fields.defs(claims, "customer"), body.fields)
    account = None
    if body.account_id:
        account = parties.account_of(claims, body.account_id)
    elif body.account_name:
        account = parties.create_account(
            claims, AccountIn(location_id=body.location_id, type=body.account_type or "", name=body.account_name)
        )
    customer = Customer.objects.create(
        tenant_id=claims.tenant_id,
        location_id=body.location_id,
        name=name,
        phone=body.phone.strip()[:40],
        email=body.email.strip()[:160],
        since=clock.today(claims.zone(body.location_id)),
        fields=values,
        account=account,
        account_role=body.account_role.strip()[:60] if account else "",
    )
    audit(claims, "customer.created", "access", name + (f" · {account.name}" if account else ""), body.location_id)
    return customer


def sell_plan(claims: TenantClaims, customer_id: str, offering_id: str) -> Customer:
    with transaction.atomic():
        customer = _get(claims, customer_id, lock=True)
        parties.sell(claims, customer, offering_id)
    return customer


def cancel_plan(claims: TenantClaims, customer_id: str, subscription_id: str) -> Customer:
    with transaction.atomic():
        customer = _get(claims, customer_id, lock=True)
        parties.cancel(claims, customer, subscription_id)
    return customer


def record_document(claims: TenantClaims, customer_id: str, body: DocumentIn) -> Customer:
    claims.demand("bookings.manage")
    with transaction.atomic():
        customer = _get(claims, customer_id, lock=True)
        documents.record(
            claims,
            customer,
            body.type,
            subject_id=body.subject_id,
            issued=body.issued,
            expires=body.expires,
            reference=body.reference,
        )
    return customer
