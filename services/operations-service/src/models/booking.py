from __future__ import annotations

import uuid

from django.db import models

from .catalog import Offering, Resource
from .customer import Customer


class Booking(models.Model):
    """A slot of someone's time, an asset's time, or a class session.

    Single bookings have a customer; class sessions have none and gather
    `Attendance` rows up to the offering's capacity.
    """

    class Status(models.TextChoices):
        REQUESTED = "requested"
        CONFIRMED = "confirmed"
        CHECKED_IN = "checked_in"
        COMPLETED = "completed"
        NO_SHOW = "no_show"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    location_id = models.UUIDField(db_index=True)
    offering = models.ForeignKey(Offering, on_delete=models.PROTECT, related_name="bookings")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="bookings")
    resources = models.ManyToManyField(Resource, related_name="bookings")
    # What the booking is for, when the offering serves a subject (a pet, a vehicle).
    subject = models.ForeignKey(
        "operations.Subject", null=True, blank=True, on_delete=models.PROTECT, related_name="bookings"
    )
    # The template's typed booking fields (docs/PLATFORM.md gap 6).
    fields = models.JSONField(default=dict, blank=True)
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start"]
        indexes = [models.Index(fields=["tenant_id", "start"])]

    def __str__(self) -> str:
        return f"{self.offering_id} {self.start:%Y-%m-%d %H:%M}"


class Attendance(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="attendances")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="attendances")
    # The pack the seat spent a credit from, so calling the session off returns it there.
    subscription = models.ForeignKey(
        "operations.Subscription", null=True, blank=True, on_delete=models.SET_NULL, related_name="seats"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["booking", "customer"], name="one_seat_per_customer")]

    def __str__(self) -> str:
        return f"{self.customer_id} @ {self.booking_id}"
