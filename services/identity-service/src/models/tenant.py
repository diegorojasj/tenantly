from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.db import models

from .account import User


class Tenant(models.Model):
    """One business. Everything any service stores is keyed by its id."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    industry = models.CharField(max_length=160, blank=True)
    template_id = models.CharField(max_length=20)
    hue = models.PositiveSmallIntegerField()
    # Legacy: the Tenantly plan as identity held it before billing owned subscriptions
    # (docs/BILLING.md). Billing imports it once per business and never writes it back;
    # both fields go once every business has a subscription in billing.
    plan = models.CharField(max_length=20, default="Starter")
    plan_terms = models.JSONField(default=dict, blank=True)
    tenant_key = models.CharField(max_length=32, unique=True)
    residency = models.CharField(max_length=32, default="us-east-1")
    # Money (gap 9): every amount the business charges is in this currency; tax is a
    # percentage, either already inside prices or added on top when invoicing.
    currency = models.CharField(max_length=3, default="USD")
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal(0))
    tax_label = models.CharField(max_length=20, default="Tax")
    prices_include_tax = models.BooleanField(default=True)
    # Branding (gap 10): a white-label tenant's logo and the domain it would be served on.
    logo_url = models.URLField(max_length=500, blank=True)
    custom_domain = models.CharField(max_length=253, null=True, blank=True, unique=True)
    # Single sign-on settings, stored only: no identity provider is contacted yet.
    sso = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.slug

    def money(self) -> dict[str, Any]:
        """The money settings, as they travel in the tenant token and to the frontend."""
        return {
            "currency": self.currency,
            "taxRate": str(Decimal(self.tax_rate).quantize(Decimal("0.01"))),
            "taxLabel": self.tax_label,
            "pricesIncludeTax": self.prices_include_tax,
        }


class Node(models.Model):
    """The location tree: the business (org), groups of any depth (region), locations.

    A group's `level` names which of the template's `levels` it is (area, franchisee,
    district…); a child group sits on a deeper level than its parent. Locations hang
    under the business or any group.
    """

    class Kind(models.TextChoices):
        ORG = "org"
        REGION = "region"
        LOCATION = "location"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="nodes")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Groups only: the template level key. Empty for the business and for locations.
    level = models.CharField(max_length=30, blank=True, default="")
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=16)
    status = models.CharField(max_length=12, default="active")
    # Locations: the IANA zone their wall clock runs in, and opening hours in
    # minutes from local midnight. Null hours mean the template's.
    tz = models.CharField(max_length=64, default="UTC")
    open = models.PositiveSmallIntegerField(null=True, blank=True)
    close = models.PositiveSmallIntegerField(null=True, blank=True)
    # Locations: a street address and the map pin (WGS84). No pin means "not on the map".
    address = models.CharField(max_length=200, blank=True, default="")
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def hours(self) -> tuple[int, int] | None:
        return (self.open, self.close) if self.open is not None and self.close is not None else None

    @property
    def pin(self) -> tuple[float, float] | None:
        return (self.lat, self.lng) if self.lat is not None and self.lng is not None else None


class Membership(models.Model):
    """A person's role in one business, limited to one node of its tree.

    An invite is a membership with an email and no user yet. It is claimed by
    signing up or in with that email *and* the one-time invite code, so
    knowing the address alone is never enough (emails aren't verified).
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        INVITED = "invited"
        SUSPENDED = "suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="memberships")
    email = models.EmailField()
    # A `Role.key` of the same tenant.
    role = models.CharField(max_length=40)
    scope = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    mfa = models.BooleanField(default=False)
    # SHA-256 of the invite code; cleared once the invite is claimed.
    invite_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "email"], name="one_membership_per_email")]

    def __str__(self) -> str:
        return f"{self.email} @ {self.tenant_id}"


class Role(models.Model):
    """A role of one business (gap 8): copied from the template's defaults when the business
    is created, then edited, added to or removed by the business itself.

    `owner` always exists, can't be edited and always holds every permission.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="roles")
    key = models.SlugField(max_length=40)
    label = models.CharField(max_length=60)
    summary = models.CharField(max_length=200, blank=True)
    permissions = models.JSONField(default=list)
    # True for roles that came from the template; false for ones the business added.
    builtin = models.BooleanField(default=False)
    # Lang -> {label?, summary?}: the template's wording in other languages, kept until
    # the business words the role itself (common/i18n.py).
    translations = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "key"]
        constraints = [models.UniqueConstraint(fields=["tenant", "key"], name="one_role_key_per_tenant")]

    def __str__(self) -> str:
        return f"{self.key} @ {self.tenant_id}"
