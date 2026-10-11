from __future__ import annotations

from typing import Any

from django.db import models

from common.i18n import localize


class Template(models.Model):
    """A business template (docs/PLATFORM.md): stored data, not code.

    It renames everything, defines the resource types that deliver the work and
    the fulfilment presets offerings start from, lists what must be known about a
    customer, sets opening hours, defines the booking lifecycle and the policies a
    new business starts with. Tenants reference it by `id`; editing a template
    bumps `version`.

    Both lists are stored in their wire shape (camelCase), like `customer_fields`:

    - `resource_types`: `{key, label, plural, people, roleLabel, attributes}`;
      `attributes` are `{key, label, type: text|number|bool|choice, options?, required?}`.
    - `presets`: `{key, label, plural, intro, capacity, time, units, place, requires}`;
      `time` is slot | window | span | none, `place` on_site | at_customer, and
      `requires` lists `{type, quantity, pick?, role?, named?}` (docs/PLATFORM.md gaps 3-4);
      a preset may also name the `subject` type every booking must be for (a pet, a vehicle).
    - `fields`: entity (customer | account | offering | booking) -> typed field definitions
      `{key, label, type: text|number|bool|choice|date, options?, required?, pii?, expires?}`;
      resource attributes and subject fields use the same shape (docs/PLATFORM.md gap 6).
    - `account_types` / `subject_types`: `{key, label, plural, fields}`: who pays (a company,
      a household) and what is served (a pet, a child, a vehicle, a property) (gap 5).
    - `documents`: `{key, label, appliesTo: customer|subject, subjectType?, validDays?}`; whether
      one is needed is the `docs.require.<key>` policy (gap 6).
    - `levels`: the named group levels of the location tree, top to bottom, between the
      business and its locations: `{key, label, plural}` (area; or region, franchisee) (gap 8).
    - `roles`: the roles a new business starts with: `{id, label, summary, permissions}` (gap 8).

    Everything above is worded in English. `translations` holds the other languages as
    `{lang: overlay}`, each overlay in the wire shape with only the words
    (`{"terms": {"customer": "Socio"}, "presets": [{"key": "class", "label": "Clase"}]}`);
    `as_dict` lays the request's language over the English (common/i18n.py).
    """

    id = models.SlugField(max_length=20, primary_key=True)
    version = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=60)
    description = models.CharField(max_length=240, blank=True)
    hue = models.PositiveSmallIntegerField()
    # Fulfilment presets an offering can start from (formerly the five fixed kinds).
    presets = models.JSONField(default=list)
    # What delivers the work: team members, rooms, units, vans…
    resource_types = models.JSONField(default=list)
    # Open map: word key -> label ("customer" -> "Member").
    terms = models.JSONField(default=dict)
    # Booking status -> label.
    status = models.JSONField(default=dict)
    # Booking status -> statuses it may move to.
    transitions = models.JSONField(default=dict)
    # Typed custom fields per entity: {"customer": [...], "account": [...], ...}.
    fields = models.JSONField(default=dict)
    # Who a customer can belong to (company, household) and what the business serves.
    account_types = models.JSONField(default=list)
    subject_types = models.JSONField(default=list)
    # Document types (waiver, vaccination, licence) and how long each stays valid.
    documents = models.JSONField(default=list)
    # Named group levels of the location tree, top to bottom (area; region → franchisee…).
    levels = models.JSONField(default=list)
    # The roles a new business starts with; it can edit them and add its own.
    roles = models.JSONField(default=list)
    open = models.PositiveSmallIntegerField()
    close = models.PositiveSmallIntegerField()
    # Policy key -> starting value; keys not listed use the platform default.
    policy_defaults = models.JSONField(default=dict)
    # Lang -> overlay of the wire shape with only the words, e.g. {"es": {"terms": {...}}}.
    translations = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label"]

    def __str__(self) -> str:
        return f"{self.id} v{self.version}"

    def as_dict(self, lang: str | None = None) -> dict[str, Any]:
        """The wire shape (camelCase), as the frontend's `Template` type reads it, in `lang`
        (the request's language by default)."""
        return localize(self.base_dict(), self.translations, lang)

    def base_dict(self) -> dict[str, Any]:
        """The wire shape in English, before any translation."""
        return {
            "id": self.id,
            "version": self.version,
            "label": self.label,
            "description": self.description,
            "hue": self.hue,
            "presets": list(self.presets),
            "resourceTypes": list(self.resource_types),
            "terms": dict(self.terms),
            "status": dict(self.status),
            "transitions": {k: list(v) for k, v in self.transitions.items()},
            "fields": {k: list(v) for k, v in self.fields.items()},
            "accountTypes": list(self.account_types),
            "subjectTypes": list(self.subject_types),
            "documents": list(self.documents),
            "levels": list(self.levels),
            "roles": list(self.roles),
            "open": self.open,
            "close": self.close,
            "policyDefaults": dict(self.policy_defaults),
        }

    def rules(self) -> dict[str, Any]:
        """What other services enforce; travels inside the tenant token, worded in the
        language of the request that issued it."""
        data = self.as_dict()
        for key in ("id", "description", "hue", "roles"):
            del data[key]
        return data
