from __future__ import annotations

import uuid

from django.db import models
from django.db.models import F, Q


def default_thresholds() -> list[int]:
    """Only a fallback: new subscriptions take the billing policy's thresholds."""
    return [80, 100]


class TenantSubscription(models.Model):
    """What a business buys from Tenantly: one row per tenant, for life (docs/BILLING.md §6).

    Stored status is only `active` or `canceled`. How far behind on payment a business is
    (past due, limited, restricted) is derived on read from its oldest unpaid invoice, so it
    can never go stale (services/standing.py).
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        CANCELED = "canceled"

    class Method(models.TextChoices):
        MANUAL = "manual"
        STRIPE = "stripe"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(unique=True)
    plan_version = models.ForeignKey("billing.PlanVersion", on_delete=models.PROTECT, related_name="+")
    # A downgrade waits for the next renewal.
    scheduled_plan_version = models.ForeignKey(
        "billing.PlanVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    # Read-only access and export until this day; then the data may be deleted.
    retention_until = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=10, choices=Method.choices, default=Method.MANUAL)
    stripe_customer_id = models.CharField(max_length=64, blank=True)
    stripe_payment_method_id = models.CharField(max_length=64, blank=True)
    # Set by the business: a period never bills past it, whatever the usage.
    spend_cap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # Percent of the allowance that sends a notice, once per period each.
    alert_thresholds = models.JSONField(default=default_thresholds)
    # The self-serve 7-day payment extension, once per 12 months.
    extension_used_on = models.DateField(null=True, blank=True)
    # Bumped on every change; a change sent against an older revision is refused.
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(spend_cap__isnull=True) | Q(spend_cap__gte=0), name="spend_cap_not_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.plan_version_id} {self.status}"


class SubscriptionChange(models.Model):
    """Append-only history of a subscription: what changed, when, who asked, and why."""

    class Kind(models.TextChoices):
        CREATED = "created"
        UPGRADE = "upgrade"
        DOWNGRADE_SCHEDULED = "downgrade_scheduled"
        DOWNGRADE_WITHDRAWN = "downgrade_withdrawn"
        DOWNGRADE_APPLIED = "downgrade_applied"
        CANCEL_SCHEDULED = "cancel_scheduled"
        CANCEL_WITHDRAWN = "cancel_withdrawn"
        CANCELED = "canceled"
        REACTIVATED = "reactivated"
        ASSIGNED = "assigned"
        SETTINGS = "settings"
        EXTENSION = "extension"
        # Tenantly published a new price list for the plan: it applies at the next renewal.
        REPRICE_SCHEDULED = "reprice_scheduled"
        REPRICE_APPLIED = "reprice_applied"

    subscription = models.ForeignKey(TenantSubscription, on_delete=models.CASCADE, related_name="changes")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    from_version = models.ForeignKey(
        "billing.PlanVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    to_version = models.ForeignKey(
        "billing.PlanVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    detail = models.JSONField(default=dict, blank=True)
    effective_at = models.DateTimeField()
    actor_id = models.CharField(max_length=64)
    actor_name = models.CharField(max_length=120)
    # The client's Idempotency-Key: a retried request finds the change it already made.
    idempotency_key = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["subscription", "effective_at"])]
        constraints = [
            models.UniqueConstraint(fields=["subscription", "idempotency_key"], name="one_change_per_key"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} @ {self.effective_at:%Y-%m-%d}"


class EntitlementGrant(models.Model):
    """An exception Tenantly authorised for one business, for a bounded time, with a reason.

    - `extra_allowance`: `value` more units of `metric` in every period it overlaps.
    - `discount_pct`: `value`% off the invoice of a period it overlaps.
    - `waive_overage`: no overage for a period it overlaps.
    - `extend_grace`: `value` more days before an unpaid invoice escalates.
    - `dispute`: an invoice is being disputed; nothing escalates while it lasts.
    """

    class Kind(models.TextChoices):
        EXTRA_ALLOWANCE = "extra_allowance"
        DISCOUNT_PCT = "discount_pct"
        WAIVE_OVERAGE = "waive_overage"
        EXTEND_GRACE = "extend_grace"
        DISPUTE = "dispute"

    tenant_id = models.UUIDField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    metric = models.CharField(max_length=30, blank=True)
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    reason = models.CharField(max_length=200)
    approved_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "valid_until"])]
        constraints = [
            models.CheckConstraint(condition=Q(valid_until__gt=F("valid_from")), name="grant_window_forward"),
            models.CheckConstraint(condition=Q(value__gte=0), name="grant_value_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.value} ({self.reason})"
