from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models


class PlanInvoice(models.Model):
    """What Tenantly bills a business for one period. Not a customer `Invoice`.

    Lines are written once, when the period closes; a correction is a credit on a later
    invoice, never an edit.
    """

    class Status(models.TextChoices):
        OPEN = "open"
        PAID = "paid"
        VOID = "void"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    period = models.OneToOneField("billing.BillingPeriod", on_delete=models.PROTECT, related_name="invoice")
    # Tenantly-wide sequence: TNT-000001…
    number = models.PositiveIntegerField(unique=True)
    currency = models.CharField(max_length=3)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    issued_at = models.DateTimeField()
    due_on = models.DateField()
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_via = models.CharField(max_length=10, blank=True)
    payment_ref = models.CharField(max_length=120, blank=True)
    # Card charges tried so far (Stripe), and why the last one failed.
    attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_on = models.DateField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-issued_at"]
        indexes = [models.Index(fields=["tenant_id", "status", "due_on"])]

    def __str__(self) -> str:
        return self.code

    @property
    def code(self) -> str:
        return f"TNT-{self.number:06d}"


class PlanInvoiceLine(models.Model):
    class Kind(models.TextChoices):
        BASE = "base"
        OVERAGE = "overage"
        CAP = "cap"
        DISCOUNT = "discount"
        CREDIT = "credit"

    invoice = models.ForeignKey(PlanInvoice, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Plan name, dates, units: everything the page needs to word the line in any language.
    detail = models.JSONField(default=dict)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["invoice", "position"], name="one_line_per_position")]

    def __str__(self) -> str:
        return f"{self.kind} {self.amount}"


class ProviderEvent(models.Model):
    """Every webhook a payment provider sent, stored before it's applied: duplicates stop here."""

    class Status(models.TextChoices):
        APPLIED = "applied"
        SKIPPED = "skipped"
        FAILED = "failed"

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=80)
    type = models.CharField(max_length=80)
    occurred_at = models.DateTimeField()
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices)
    note = models.CharField(max_length=200, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "event_id"], name="one_provider_event")]

    def __str__(self) -> str:
        return f"{self.provider} {self.type} {self.event_id}"


class BillingNotice(models.Model):
    """Something the owner should know about their Tenantly plan, shown on the page.

    `key` makes each notice happen once (a threshold once per period, a reminder once per
    invoice and stage). `params` carry the numbers; the page words them in the reader's language.
    """

    tenant_id = models.UUIDField()
    kind = models.CharField(max_length=30)
    key = models.CharField(max_length=120)
    params = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["tenant_id", "key"], name="one_notice_per_key")]

    def __str__(self) -> str:
        return f"{self.kind} {self.key}"
