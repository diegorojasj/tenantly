from __future__ import annotations

import uuid

from django.db import models

from .catalog import Offering
from .customer import Customer


class Account(models.Model):
    """Who a group of customers belongs to (docs/PLATFORM.md gap 5): a company with contacts, a household.

    `type` is a key of the template's account types; its members are the customers
    pointing at it, each with a free-text `account_role` (Billing contact, Parent…).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    location_id = models.UUIDField(db_index=True)
    type = models.CharField(max_length=30)
    name = models.CharField(max_length=160)
    fields = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Subject(models.Model):
    """What the business serves for a customer: a pet, a child, a vehicle, a property (gap 5).

    `type` is a key of the template's subject types, whose typed fields fill `fields`.
    It belongs to one customer or to an account (a household's car, a company's site);
    an offering may require one, and a booking then names it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    location_id = models.UUIDField(db_index=True)
    type = models.CharField(max_length=30)
    name = models.CharField(max_length=160)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.CASCADE, related_name="subjects")
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.CASCADE, related_name="subjects")
    fields = models.JSONField(default=dict)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Subscription(models.Model):
    """A plan a customer holds; a customer may hold several (gap 5).

    Monthly plans run until `renews`; packs carry `credits`, spent one per class seat.
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="subscriptions")
    offering = models.ForeignKey(Offering, on_delete=models.PROTECT, related_name="subscriptions")
    started = models.DateField()
    renews = models.DateField(null=True, blank=True)
    credits = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.offering_id} → {self.customer_id}"


class Document(models.Model):
    """A document on file for a customer, or for one of their subjects (gap 6): a waiver, a vaccination.

    `type` is a key of the template's document types. It is valid on a day when that day
    falls between `issued` and `expires` (no `expires`: valid for good).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="documents")
    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.CASCADE, related_name="documents")
    type = models.CharField(max_length=30)
    issued = models.DateField()
    expires = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    recorded_by = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued", "-created_at"]

    def __str__(self) -> str:
        return f"{self.type} · {self.customer_id}"
