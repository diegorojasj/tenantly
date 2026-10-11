"""Documents with expiry (docs/PLATFORM.md gap 6), replacing the single waiver flag.

The template lists document types: `{key, label, appliesTo: customer | subject,
subjectType?, validDays?}`. Whether one is needed at a location is the
`docs.require.<key>` policy, inherited down the tree like any other:

- "Not needed": nothing happens;
- "Remind": customers without a valid one are flagged on their profile and in
  Today's arrivals (what the waiver flag used to do);
- "Required to book": booking, or joining a session, is refused until one is on file
  and still valid on the day of the booking.

A subject document (a vaccination) is checked against the booking's subject, so it
only applies when the offering serves that subject type.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils.translation import gettext as _

from common.errors import InvalidError
from common.internal import audit

from ..models import Customer, Document, Subject
from . import clock, parties, policies

if TYPE_CHECKING:
    from common.auth import TenantClaims

OFF, REMIND, BLOCK = policies.DOC_LEVELS
PREFIX = policies.DOC_PREFIX


def types(claims: TenantClaims) -> list[dict[str, Any]]:
    return list(claims.template.get("documents") or [])


def type_of(claims: TenantClaims, key: str) -> dict[str, Any] | None:
    return next((d for d in types(claims) if d.get("key") == key), None)


def level(claims: TenantClaims, location_id: str, key: str) -> str:
    value = policies.effective(claims, location_id, PREFIX + key)
    return value if value in policies.DOC_LEVELS else OFF


def valid(doc: Document, on: date) -> bool:
    return doc.issued <= on and (doc.expires is None or doc.expires >= on)


def doc_dict(claims: TenantClaims, doc: Document, today: date) -> dict[str, Any]:
    kind = type_of(claims, doc.type) or {}
    return {
        "id": str(doc.id),
        "type": doc.type,
        "label": kind.get("label", doc.type),
        "subjectId": str(doc.subject_id) if doc.subject_id else None,
        "issued": doc.issued.isoformat(),
        "expires": doc.expires.isoformat() if doc.expires else None,
        "reference": doc.reference,
        "valid": valid(doc, today),
    }


def rules_at(claims: TenantClaims, location_id: str) -> dict[str, str]:
    """Document type -> how much the policy at this location asks for it (omitting "Not needed")."""
    out = {}
    for kind in types(claims):
        needed = level(claims, location_id, kind["key"])
        if needed != OFF:
            out[kind["key"]] = needed
    return out


def missing(
    claims: TenantClaims,
    customer: Customer,
    on: date,
    rules: dict[str, str],
    *,
    subject: Subject | None = None,
    levels: tuple[str, ...] = (REMIND, BLOCK),
) -> list[dict[str, Any]]:
    """Document types `rules` ask of this customer (and the subject, if any) with none valid on `on`.

    Customer documents are always checked; subject documents only for the given subject.
    """
    held = list(customer.documents.all())
    out = []
    for kind in types(claims):
        if rules.get(kind["key"]) not in levels:
            continue
        if kind.get("appliesTo") == "subject":
            if not subject or (kind.get("subjectType") and kind["subjectType"] != subject.type):
                continue
            pool = [d for d in held if d.subject_id == subject.id]
        else:
            pool = [d for d in held if d.subject_id is None]
        if not any(d.type == kind["key"] and valid(d, on) for d in pool):
            out.append(kind)
    return out


def demand(claims: TenantClaims, customer: Customer, on: date, at: str, subject: Subject | None = None) -> None:
    """Refuse a booking when a document the policy requires to book is missing or expired that day."""
    lacking = missing(claims, customer, on, rules_at(claims, at), subject=subject, levels=(BLOCK,))
    if lacking:
        what = ", ".join(k["label"].lower() for k in lacking)
        msg = _("%(customer)s needs a valid %(documents)s on file before booking") % {
            "customer": customer.name,
            "documents": what,
        }
        raise InvalidError(msg)


@transaction.atomic
def record(
    claims: TenantClaims,
    customer: Customer,
    key: str,
    *,
    subject_id: str | None = None,
    issued: str | None = None,
    expires: str | None = None,
    reference: str = "",
) -> Document:
    kind = type_of(claims, key)
    if not kind:
        msg = _("Unknown document type")
        raise InvalidError(msg)
    subject = None
    if kind.get("appliesTo") == "subject":
        # Only the customer's own subjects and their account's (compared as text: ids come from the form).
        subject = next((x for x in parties.subjects_of(customer) if str(x.id) == (subject_id or "")), None)
        if not subject:
            msg = _("Pick which of %(customer)s's %(subjects)s it is for") % {
                "customer": customer.name,
                "subjects": kind.get("subjectType") or _("subjects"),
            }
            raise InvalidError(msg)
        if kind.get("subjectType") and subject.type != kind["subjectType"]:
            msg = _("A %(document)s is for a %(subject)s") % {
                "document": kind["label"].lower(),
                "subject": kind["subjectType"],
            }
            raise InvalidError(msg)
    today = clock.today(claims.zone(str(customer.location_id)))
    try:
        on = date.fromisoformat(issued) if issued else today
        until = date.fromisoformat(expires) if expires else None
    except ValueError:
        msg = _("Dates must be YYYY-MM-DD")
        raise InvalidError(msg) from None
    if on > today:
        msg = _("A document can't be issued in the future")
        raise InvalidError(msg)
    if until is None and kind.get("validDays"):
        until = on + timedelta(days=int(kind["validDays"]))
    if until is not None and until < on:
        msg = _("It can't expire before it was issued")
        raise InvalidError(msg)
    doc = Document.objects.create(
        tenant_id=claims.tenant_id,
        customer=customer,
        subject=subject,
        type=key,
        issued=on,
        expires=until,
        reference=reference.strip()[:120],
        recorded_by=claims.user_name,
    )
    target = f"{kind['label']} · {customer.name}" + (f" · {subject.name}" if subject else "")
    audit(claims, "document.recorded", "access", target, str(customer.location_id))
    return doc
