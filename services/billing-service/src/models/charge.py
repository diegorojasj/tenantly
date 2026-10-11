from __future__ import annotations

import uuid

from django.db import models


class Charge(models.Model):
    """Money a customer owes or paid for one thing: a booking, a drop-in, a plan.

    Stored states are due / paid / refunded. "Overdue" is derived on read from
    the age of a due charge, so it can never go stale.
    """

    class Status(models.TextChoices):
        DUE = "due"
        PAID = "paid"
        REFUNDED = "refunded"

    class Source(models.TextChoices):
        BOOKING = "booking"
        DROPIN = "dropin"
        PLAN = "plan"
        FEE = "fee"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    location_id = models.UUIDField()
    customer_id = models.UUIDField(db_index=True)
    # A snapshot, so the payments list never needs another service to render.
    customer_name = models.CharField(max_length=160)
    booking_id = models.UUIDField(null=True, blank=True, db_index=True)
    description = models.CharField(max_length=200)
    source = models.CharField(max_length=10, choices=Source.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    # The tenant's currency when the charge was raised (a snapshot, like the name).
    currency = models.CharField(max_length=3, default="USD")
    # Set once the charge is put on a customer invoice; cleared if the invoice is voided.
    invoice = models.ForeignKey(
        "billing.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="charges"
    )
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices)
    paid_on = models.DateField(null=True, blank=True)
    # Set by the caller so a retried request can't raise the same charge twice.
    key = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "date"])]
        constraints = [models.UniqueConstraint(fields=["tenant_id", "key"], name="one_charge_per_key")]

    def __str__(self) -> str:
        return f"{self.description} {self.amount} {self.status}"
