from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models
from django.db.models import Q

# The fields a version's price is made of: frozen once the version is offered.
PRICED = ("currency", "base_price", "included", "overage_price", "overage_cap")


class PlanVersion(models.Model):
    """One priced edition of a Tenantly plan (docs/BILLING.md §6). Immutable once offered.

    A price change is a new version, never an edit, so an invoice can always say what it was
    priced on. `active` versions are offered to new subscribers, `legacy` ones are honoured for
    the tenants already on them. A Custom plan is a private version (`tenant_id` set).
    """

    class Status(models.TextChoices):
        DRAFT = "draft"
        ACTIVE = "active"
        LEGACY = "legacy"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40)
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=60)
    # Set for a Custom plan: only that business may hold it.
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)
    currency = models.CharField(max_length=3, default="USD")
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    # Per metric: units the base price covers each period. A metric left out has no limit.
    included = models.JSONField(default=dict, blank=True)
    # Per metric: decimal string per unit past the allowance. A metric left out has no overage.
    overage_price = models.JSONField(default=dict, blank=True)
    # The period total never passes this (the next tier's price). Null: the tenant's spend cap.
    overage_cap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # Upgrade / downgrade order.
    rank = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    effective_from = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rank", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["code", "version"], name="one_plan_version_number"),
            models.CheckConstraint(condition=Q(base_price__gte=0), name="plan_price_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk:
            stored = PlanVersion.objects.filter(pk=self.pk).first()
            if stored and stored.status != self.Status.DRAFT:
                changed = [f for f in PRICED if getattr(stored, f) != getattr(self, f)]
                if changed:
                    msg = f"Plan version {stored} is offered: publish a new version instead of changing {changed}"
                    raise ValueError(msg)
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def allowance(self, metric: str) -> int | None:
        value = self.included.get(metric)
        return None if value is None else int(value)

    def unit_price(self, metric: str) -> Decimal | None:
        value = self.overage_price.get(metric)
        return None if value is None else Decimal(str(value))
