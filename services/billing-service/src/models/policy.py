from __future__ import annotations

from django.db import models


class BillingPolicy(models.Model):
    """The rules collections and pricing follow (docs/BILLING.md §5.1), one row per edit.

    Rows are never changed: an edit is a new row with the next `version`, who made it and why.
    The newest row whose `effective_at` has passed is the policy in force (services/policy.py).
    """

    version = models.PositiveIntegerField(unique=True)
    # Days after an unpaid invoice's due date: no new customers, then no new bookings, then canceled.
    limit_after_days = models.PositiveSmallIntegerField()
    restrict_after_days = models.PositiveSmallIntegerField()
    cancel_after_days = models.PositiveSmallIntegerField()
    # Days to pay an invoice settled by transfer (cards are charged on issue).
    payment_terms_days = models.PositiveSmallIntegerField()
    # An unpaid balance below this never escalates past `past_due`.
    small_balance = models.DecimalField(max_digits=10, decimal_places=2)
    # The self-serve payment extension: how many days, and how often.
    extension_days = models.PositiveSmallIntegerField()
    extension_every_days = models.PositiveSmallIntegerField()
    # Read-only access and export after cancellation.
    retention_days = models.PositiveSmallIntegerField()
    # How long an ended period takes late usage before it's invoiced.
    usage_grace_hours = models.PositiveSmallIntegerField()
    # A top-tier period with no cap of its own bills at most this many times its base price.
    spend_cap_multiple = models.DecimalField(max_digits=5, decimal_places=2)
    # Percent of the allowance that sends a notice; what new subscriptions start with.
    alert_thresholds = models.JSONField()
    effective_at = models.DateTimeField()
    edited_by_id = models.CharField(max_length=64)
    edited_by = models.CharField(max_length=120)
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"billing policy v{self.version}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk:
            msg = "A billing policy is never edited in place: save a new version"
            raise ValueError(msg)
        super().save(*args, **kwargs)  # type: ignore[arg-type]
