from __future__ import annotations

import uuid

from django.db import models


class Offering(models.Model):
    """What a business sells, and the fulfilment rules it books under (docs/PLATFORM.md gap 3).

    `kind` only names the template preset the offering started from (for grouping
    and badges); behaviour follows the rules: `capacity` (1 = one customer per
    booking, N = a shared session), `time`, `place` and the `requires` list.
    """

    class Time(models.TextChoices):
        SLOT = "slot"  # a fixed length (`minutes`)
        WINDOW = "window"  # the customer picks the length on one day, priced by the hour
        SPAN = "span"  # whole local days, nights or months
        NONE = "none"  # not booked on the calendar: plans

    class Place(models.TextChoices):
        ON_SITE = "on_site"
        AT_CUSTOMER = "at_customer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    # The template preset it was created from (appointment, class, rental, visit, plan, …).
    kind = models.CharField(max_length=20)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=60, default="General")
    minutes = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    # session | hour | day | night | month | pack (plans: month | pack)
    unit = models.CharField(max_length=8)
    # Customers per booking: 1 books a slot, more makes a session people join. None for plans.
    capacity = models.PositiveIntegerField(null=True, blank=True)
    credits = models.PositiveIntegerField(null=True, blank=True)
    time = models.CharField(max_length=6, choices=Time.choices, default=Time.SLOT)
    place = models.CharField(max_length=12, choices=Place.choices, default=Place.ON_SITE)
    # What every booking takes: [{type, quantity, pick, role, where}] (services/fulfilment.py).
    requires = models.JSONField(default=list)
    # The subject type every booking must name (a pet, a vehicle); blank when it serves the customer.
    subject_type = models.CharField(max_length=30, blank=True)
    # The template's typed offering fields (docs/PLATFORM.md gap 6).
    fields = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def shared(self) -> bool:
        """Booked as a session many customers join, rather than one slot per customer."""
        return (self.capacity or 1) > 1


class Resource(models.Model):
    """Who or what delivers the work at one location (docs/PLATFORM.md gap 4).

    `type` is a key of the template's resource types (`staff`, `asset`, `chair`…);
    `role` is its free-text category (a specialty, or Kayak / Room / Van) that
    requirements match on, and `attributes` hold the type's typed fields. A
    resource may sit inside another at the same location (property → unit):
    booking either one blocks the other.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    location_id = models.UUIDField(db_index=True)
    type = models.CharField(max_length=30)
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=60)
    attributes = models.JSONField(default=dict, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    status = models.CharField(max_length=16, default="available")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["type", "created_at"]

    def __str__(self) -> str:
        return self.name
