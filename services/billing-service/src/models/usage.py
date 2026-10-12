from __future__ import annotations

from django.db import models
from django.db.models import F, Q


class BillingPeriod(models.Model):
    """A month of one subscription: `[starts_at, ends_at)` in UTC (docs/BILLING.md §5).

    `open` takes usage; `closing` has ended and still takes usage that was late on the way
    (the grace window); `invoiced` is frozen. `held` failed reconciliation and waits for staff.
    `segments` lists the plan versions in force and since when, so an upgrade prorates.
    """

    class Status(models.TextChoices):
        OPEN = "open"
        CLOSING = "closing"
        INVOICED = "invoiced"
        HELD = "held"

    tenant_id = models.UUIDField(db_index=True)
    subscription = models.ForeignKey("billing.TenantSubscription", on_delete=models.PROTECT, related_name="periods")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    # [{"version": "<plan version id>", "from": "<iso datetime>"}], oldest first.
    segments = models.JSONField(default=list)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "starts_at"], name="one_period_per_start"),
            models.UniqueConstraint(fields=["tenant_id"], condition=Q(status="open"), name="one_open_period"),
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="period_ends_after_start"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.starts_at:%Y-%m-%d} {self.status}"

    @property
    def takes_usage(self) -> bool:
        return self.status in {self.Status.OPEN, self.Status.CLOSING}


class UsageRecord(models.Model):
    """The append-only evidence behind every count: one row per event operations sent.

    `delta` +1 serves a subject, -1 reverses that (a class called off). The same source can
    count once and be reversed once, whatever key it arrives under.
    """

    tenant_id = models.UUIDField()
    period = models.ForeignKey(BillingPeriod, on_delete=models.PROTECT, related_name="records")
    metric = models.CharField(max_length=30)
    subject_key = models.CharField(max_length=64)
    # A snapshot (the customer's name), so the evidence reads without another service.
    label = models.CharField(max_length=160, blank=True)
    source = models.CharField(max_length=30)
    source_ref = models.CharField(max_length=100)
    delta = models.SmallIntegerField()
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    # Arrived after its period was invoiced: kept as evidence, never billed.
    late = models.BooleanField(default=False)
    idempotency_key = models.CharField(max_length=64)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["period", "metric", "subject_key"]),
            models.Index(fields=["tenant_id", "occurred_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "idempotency_key"], name="one_usage_per_key"),
            models.UniqueConstraint(
                fields=["tenant_id", "metric", "source_ref", "delta"], name="one_effect_per_source"
            ),
            models.CheckConstraint(condition=Q(delta__in=(-1, 1)), name="usage_delta_unit"),
        ]

    def __str__(self) -> str:
        return f"{self.metric} {self.subject_key} {self.delta:+d}"


class ActiveSubject(models.Model):
    """One subject (a customer) counted in a period, and how many live sources keep it counted.

    The unique row is what makes a distinct count safe under concurrent requests.
    """

    period = models.ForeignKey(BillingPeriod, on_delete=models.CASCADE, related_name="subjects")
    metric = models.CharField(max_length=30)
    subject_key = models.CharField(max_length=64)
    label = models.CharField(max_length=160, blank=True)
    sources = models.PositiveIntegerField(default=0)
    first_seen_at = models.DateTimeField()
    first_source = models.CharField(max_length=30)
    first_ref = models.CharField(max_length=100)

    class Meta:
        ordering = ["first_seen_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["period", "metric", "subject_key"], name="one_subject_per_period"),
        ]

    def __str__(self) -> str:
        return f"{self.metric} {self.subject_key} x{self.sources}"


class UsageCounter(models.Model):
    """The running total the page and the invoice read: subjects with at least one live source."""

    tenant_id = models.UUIDField()
    period = models.ForeignKey(BillingPeriod, on_delete=models.CASCADE, related_name="counters")
    metric = models.CharField(max_length=30)
    quantity = models.PositiveIntegerField(default=0)
    # Alert thresholds (percent) already announced this period.
    notified = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["period", "metric"], name="one_counter_per_metric"),
        ]

    def __str__(self) -> str:
        return f"{self.metric} = {self.quantity}"
