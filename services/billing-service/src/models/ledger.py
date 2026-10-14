from __future__ import annotations

import uuid

from django.db import models


class Entry(models.Model):
    """Money the business spent or earned outside its charges: a repair bill, rent, an insurance payout.

    Charges are what customers owe; entries are everything else, so the books show
    net = revenue - expenses + other income. An entry may come from a downtime in
    operations (`source` downtime, `ref_id` its id) or be typed in on the Payments
    page (`manual`). Entries are never edited: a mistake is voided and entered again.
    """

    class Kind(models.TextChoices):
        INCOME = "income"
        EXPENSE = "expense"

    class Source(models.TextChoices):
        MANUAL = "manual"
        DOWNTIME = "downtime"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    location_id = models.UUIDField()
    kind = models.CharField(max_length=8, choices=Kind.choices)
    # Free text the business groups by: repair, maintenance, rent, supplies, insurance…
    category = models.CharField(max_length=40)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    date = models.DateField()
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    # What it was recorded against (a downtime's id), for reading it back from there.
    ref_id = models.UUIDField(null=True, blank=True, db_index=True)
    # Income charged to a customer: the charge counts it, so totals leave it out.
    charged = models.BooleanField(default=False)
    recorded_by = models.CharField(max_length=160, blank=True)
    voided = models.BooleanField(default=False)
    # Set by the caller so a retried request can't record the same line twice.
    key = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["tenant_id", "date"])]
        constraints = [models.UniqueConstraint(fields=["tenant_id", "key"], name="one_entry_per_key")]

    def __str__(self) -> str:
        return f"{self.kind} {self.amount} {self.description}"
