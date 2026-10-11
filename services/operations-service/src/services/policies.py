"""Policies: rules for booking, payments, reminders and documents.

A value set at a node applies to everything beneath it; the deepest value on
a location's path wins. The template decides the starting value (a gym asks for
signed waivers, a field crew doesn't), so a brand-new business is sensible
without anyone touching this page.

Besides the fixed rules below, every document type the template lists gets its
own `docs.require.<key>` rule (services/documents.py): Not needed, Remind, or
Required to book.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils.functional import Promise
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, pgettext_lazy

from common.errors import ForbiddenError, InvalidError
from common.internal import audit

from ..models import PolicyOverride

if TYPE_CHECKING:
    from common.auth import TenantClaims

Value = bool | int | float | str

BOOKING, PAYMENTS, REMINDERS, DOCUMENTS = (
    gettext_lazy("Booking"),
    gettext_lazy("Payments"),
    gettext_lazy("Reminders"),
    gettext_lazy("Documents"),
)

# Labels, hints, groups and units are words (translated per request); `options`
# are the stored values, worded for people by `OPTION_LABELS`.
DEFS: list[dict[str, Any]] = [
    {
        "key": "booking.approval", "label": gettext_lazy("Approve new bookings"), "group": BOOKING, "type": "bool",
        "hint": gettext_lazy("New bookings start as requests until the desk confirms them."),
        "guard": "config.write",
    },
    {
        "key": "booking.window", "label": gettext_lazy("Booking window"), "group": BOOKING, "type": "number",
        "unit": gettext_lazy("days"), "max": 365,
        "hint": gettext_lazy("How far ahead customers can book."), "guard": "config.write",
    },
    {
        "key": "booking.cancelHours", "label": gettext_lazy("Free cancellation until"), "group": BOOKING,
        "type": "number", "unit": gettext_lazy("h before"), "max": 720,
        "hint": gettext_lazy("Later cancellations are charged the no-show fee."), "guard": "config.write",
    },
    {
        "key": "booking.grace", "label": gettext_lazy("Check-in grace"), "group": BOOKING, "type": "number",
        "unit": gettext_lazy("min"), "max": 1440,
        "hint": gettext_lazy("Minutes after start before a booking can be marked no-show."),
        "guard": "config.write",
    },
    {
        "key": "payments.deposit", "label": gettext_lazy("Deposit at booking"), "group": PAYMENTS, "type": "number",
        "unit": "%", "max": 100,
        "hint": gettext_lazy("Share of the price collected when booking."), "guard": "pricing.write",
    },
    {
        "key": "payments.noShowFee", "label": gettext_lazy("No-show fee"), "group": PAYMENTS, "type": "enum",
        "options": ["None", "25% of price", "50% of price", "Full price"],
        "hint": gettext_lazy("Charged on no-shows and late cancellations."), "guard": "pricing.write",
    },
    {
        "key": "reminders.timing", "label": gettext_lazy("Reminder timing"), "group": REMINDERS, "type": "enum",
        "options": ["Off", "24h before", "2h before", "24h and 2h before"],
        "hint": gettext_lazy("When customers get their booking reminder."), "guard": "config.write",
    },
    {
        "key": "reminders.sms", "label": gettext_lazy("SMS reminders"), "group": REMINDERS, "type": "bool",
        "hint": gettext_lazy("Send reminders by SMS as well as email."), "guard": "config.write",
    },
    {
        "key": "docs.prefix", "label": gettext_lazy("Invoice prefix"), "group": DOCUMENTS, "type": "text",
        "hint": gettext_lazy("Prepended to invoice numbers."), "guard": "config.write",
    },
]  # fmt: skip

PLATFORM: dict[str, Value] = {
    "booking.approval": False,
    "booking.window": 14,
    "booking.cancelHours": 12,
    "booking.grace": 15,
    "payments.deposit": 0,
    "payments.noShowFee": "None",
    "reminders.timing": "24h before",
    "reminders.sms": False,
    "docs.prefix": "INV",
}

DOC_PREFIX = "docs.require."
DOC_OFF = "Not needed"
DOC_LEVELS = [DOC_OFF, "Remind", "Required to book"]

# How each stored option value reads in the request's language.
OPTION_LABELS: dict[str, Promise] = {
    "None": pgettext_lazy("no-show fee", "None"),
    "25% of price": pgettext_lazy("no-show fee", "25% of price"),
    "50% of price": pgettext_lazy("no-show fee", "50% of price"),
    "Full price": pgettext_lazy("no-show fee", "Full price"),
    "Off": pgettext_lazy("reminder timing", "Off"),
    "24h before": pgettext_lazy("reminder timing", "24h before"),
    "2h before": pgettext_lazy("reminder timing", "2h before"),
    "24h and 2h before": pgettext_lazy("reminder timing", "24h and 2h before"),
    DOC_OFF: pgettext_lazy("document requirement", "Not needed"),
    "Remind": pgettext_lazy("document requirement", "Remind"),
    "Required to book": pgettext_lazy("document requirement", "Required to book"),
}


def defs(claims: TenantClaims) -> list[dict[str, Any]]:
    """The fixed rules, plus one per document type the template lists."""
    documents = []
    for d in claims.template.get("documents") or []:
        if not d.get("key"):
            continue
        hint = (
            _("Remind flags customers without a valid one; Required to book refuses the booking. Valid for %(n)s days.")
            % {"n": d["validDays"]}
            if d.get("validDays")
            else _("Remind flags customers without a valid one; Required to book refuses the booking.")
        )
        documents.append(
            {
                "key": DOC_PREFIX + d["key"],
                "label": _("Require %(document)s") % {"document": d["label"].lower()},
                "group": DOCUMENTS,
                "type": "enum",
                "options": DOC_LEVELS,
                "hint": hint,
                "guard": "config.write",
            }
        )
    return [*DEFS, *documents]


def _public(definition: dict[str, Any]) -> dict[str, Any]:
    """A definition as the API sends it: words resolved to the request's language, option values labelled."""
    out = {k: str(v) if isinstance(v, Promise) else v for k, v in definition.items()}
    if "options" in out:
        out["options"] = list(out["options"])
        out["optionLabels"] = {o: str(OPTION_LABELS.get(o, o)) for o in out["options"]}
    return out


def default(claims: TenantClaims, key: str) -> Value:
    """The starting value for this kind of business: the template's, else the platform's."""
    fallback = DOC_OFF if key.startswith(DOC_PREFIX) else PLATFORM[key]
    return claims.template.get("policyDefaults", {}).get(key, fallback)


def effective(claims: TenantClaims, node_id: str, key: str) -> Value:
    path = [n.id for n in claims.ancestry(node_id)]
    overrides = {
        str(o.node_id): o.value
        for o in PolicyOverride.objects.filter(tenant_id=claims.tenant_id, node_id__in=path, key=key)
    }
    value = default(claims, key)
    for nid in path:
        if nid in overrides:
            value = overrides[nid]
    return value


def read(claims: TenantClaims, scope: str | None) -> list[dict[str, Any]]:
    claims.demand_any(("config.write", "pricing.write", "analytics.view"))
    focus = claims.focus(scope)
    path = claims.ancestry(focus)
    overrides = {
        (str(o.node_id), o.key): o.value
        for o in PolicyOverride.objects.filter(tenant_id=claims.tenant_id, node_id__in=[n.id for n in path])
    }
    label = claims.template["label"]
    out = []
    for d in defs(claims):
        trail = [
            {
                "nodeId": None,
                "label": _("Default for %(business)s") % {"business": label},
                "kind": "platform",
                "value": default(claims, d["key"]),
            }
        ]
        trail += [
            {"nodeId": n.id, "label": n.name, "kind": n.kind, "value": overrides.get((n.id, d["key"]))} for n in path
        ]
        source = max(i for i, step in enumerate(trail) if step["value"] is not None)
        out.append(
            {
                "def": _public(d),
                "value": trail[source]["value"],
                "source": source,
                "trail": trail,
                "editable": claims.can(d["guard"]),
            }
        )
    return out


def _check(definition: dict[str, Any], value: Value) -> Value:
    kind = definition["type"]
    if kind == "bool" and isinstance(value, bool):
        return value
    is_number = isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "number" and is_number and 0 <= value <= definition["max"]:
        return value
    if kind == "enum" and value in definition["options"]:
        return value
    if kind == "text" and isinstance(value, str) and 0 < len(value.strip()) <= 12:  # noqa: PLR2004
        return value.strip()
    msg = _("That isn't a valid value for “%(setting)s”") % {"setting": definition["label"]}
    raise InvalidError(msg)


@transaction.atomic
def write(claims: TenantClaims, scope: str, key: str, value: Value | None) -> None:
    definition = next((d for d in defs(claims) if d["key"] == key), None)
    if not definition:
        msg = _("Unknown policy")
        raise InvalidError(msg)
    claims.demand(definition["guard"])
    if claims.focus(scope) != scope:
        msg = _("That place is outside your scope")
        raise ForbiddenError(msg)
    if value is None:
        PolicyOverride.objects.filter(tenant_id=claims.tenant_id, node_id=scope, key=key).delete()
        target = f"{key} reset to inherited"
    else:
        clean = _check(definition, value)
        PolicyOverride.objects.update_or_create(
            tenant_id=claims.tenant_id, node_id=scope, key=key, defaults={"value": clean}
        )
        target = f"{key} = {clean}"
    audit(claims, "setting.overridden" if value is not None else "setting.inherited", "config", target, scope)
