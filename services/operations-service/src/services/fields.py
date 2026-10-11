"""Typed custom fields (docs/PLATFORM.md gap 6).

The template defines what a business wants to know about each entity:
`template.fields[entity]` for customers, accounts, offerings and bookings, a
subject type's `fields`, a resource type's `attributes`. Every definition has
the same shape:

    {key, label, type: text | number | bool | choice | date, options?, required?, pii?, expires?}

- `required` refuses a write without a value;
- `options` lists a `choice` field's allowed values;
- `pii` marks personal data: hidden from roles that don't serve customers
  (only `bookings.manage` sees it);
- `expires` marks a `date` field as a validity date ("vaccinated until"); it is
  reported as expired once that day has passed.

Values are stored as a plain `{key: value}` map next to the entity.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.utils.translation import gettext as _

from common.errors import InvalidError

if TYPE_CHECKING:
    from common.auth import TenantClaims

TYPES = ("text", "number", "bool", "choice", "date")
ENTITIES = ("customer", "account", "offering", "booking")
MAX_TEXT = 120
SEES_PII = "bookings.manage"


def defs(claims: TenantClaims, entity: str) -> list[dict[str, Any]]:
    """The template's field definitions for one entity (customer, account, offering, booking)."""
    return list((claims.template.get("fields") or {}).get(entity) or [])


def clean(definitions: list[dict[str, Any]], values: dict[str, Any] | None) -> dict[str, Any]:
    """Validate `values` against `definitions`: unknown keys are refused, required ones demanded, types coerced."""
    values = values or {}
    by_key = {d["key"]: d for d in definitions}
    unknown = set(values) - set(by_key)
    if unknown:
        msg = _("Unknown field: %(fields)s") % {"fields": ", ".join(sorted(unknown))}
        raise InvalidError(msg)
    out: dict[str, Any] = {}
    for key, d in by_key.items():
        value = values.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if d.get("required"):
                msg = _("Enter %(field)s") % {"field": d["label"].lower()}
                raise InvalidError(msg)
            continue
        out[key] = typed(d, value)
    return out


def typed(d: dict[str, Any], value: Any) -> Any:
    label, kind = d["label"], d.get("type", "text")
    if kind == "number":
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            number = None
        if number is None or isinstance(value, bool) or not number.is_finite():
            msg = _("%(field)s must be a number") % {"field": label}
            raise InvalidError(msg)
        return int(number) if number == number.to_integral_value() else float(number)
    if kind == "bool":
        if not isinstance(value, bool):
            msg = _("%(field)s must be yes or no") % {"field": label}
            raise InvalidError(msg)
        return value
    if kind == "date":
        try:
            return date.fromisoformat(str(value).strip()[:10]).isoformat()
        except ValueError:
            msg = _("%(field)s must be a date (YYYY-MM-DD)") % {"field": label}
            raise InvalidError(msg) from None
    text = str(value).strip()[:MAX_TEXT]
    if kind == "choice" and text not in (d.get("options") or []):
        msg = _("%(field)s must be one of: %(options)s") % {
            "field": label,
            "options": ", ".join(d.get("options") or []),
        }
        raise InvalidError(msg)
    return text


def expired(definitions: list[dict[str, Any]], values: dict[str, Any], on: date) -> list[str]:
    """Keys of `expires` date fields whose date is before `on`."""
    out = []
    for d in definitions:
        value = values.get(d["key"])
        if d.get("expires") and isinstance(value, str):
            try:
                if date.fromisoformat(value) < on:
                    out.append(d["key"])
            except ValueError:
                continue
    return out


def visible(claims: TenantClaims, definitions: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    """The values this viewer may see: personal data only for roles that serve customers."""
    if claims.can(SEES_PII):
        return dict(values)
    hidden = {d["key"] for d in definitions if d.get("pii")}
    return {k: v for k, v in values.items() if k not in hidden}


def summary(claims: TenantClaims, definitions: list[dict[str, Any]], values: dict[str, Any]) -> str:
    """One line to tell two people apart in a picker: the first visible value, in definition order."""
    shown = visible(claims, definitions, values)
    return next((str(shown[d["key"]]) for d in definitions if shown.get(d["key"]) not in {None, ""}), "")
