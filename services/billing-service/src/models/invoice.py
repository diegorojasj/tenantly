from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models


class Invoice(models.Model):
    """A customer invoice (docs/PLATFORM.md gap 9): open charges gathered under one number.

    Currency and tax are snapshots of the tenant's settings when it was issued, so changing
    them later never rewrites an invoice. With `prices_include_tax` the charges already hold
    the tax and the invoice shows the share; otherwise the tax is added on top.
    """

    class Status(models.TextChoices):
        OPEN = "open"
        PAID = "paid"
        VOID = "void"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    # Sequential per tenant: INV-0001, INV-0002…
    number = models.PositiveIntegerField()
    location_id = models.UUIDField()
    customer_id = models.UUIDField(db_index=True)
    customer_name = models.CharField(max_length=160)
    currency = models.CharField(max_length=3)
    tax_label = models.CharField(max_length=20)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    prices_include_tax = models.BooleanField()
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    issued_on = models.DateField()
    paid_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["tenant_id", "number"], name="one_invoice_number_per_tenant")]

    def __str__(self) -> str:
        return self.code

    @property
    def code(self) -> str:
        return f"INV-{self.number:04d}"
