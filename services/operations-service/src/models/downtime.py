from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from .catalog import Offering, Resource


class Downtime(models.Model):
    """A while when something can't be booked: a repair, maintenance, a closure, a team member away.

    It covers one resource (and everything nested with it), one offering at the
    location, or — with neither — the whole location. No `end` means until someone
    ends it. Bookings already inside the window are kept and flagged so the desk
    decides; new ones are refused. What it cost or earned goes to billing's ledger.
    """

    class Reason(models.TextChoices):
        MAINTENANCE = "maintenance", _("Maintenance")
        REPAIR = "repair", _("Repair")
        # Damaged, unsafe, failed an inspection.
        UNFIT = "unfit", _("Unsuitable for use")
        # A team member away: sick, on leave.
        ABSENCE = "absence", _("Absence")
        # The site is shut: flood, power cut, holiday.
        CLOSURE = "closure", _("Closure")
        OTHER = "other", _("Other")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    location_id = models.UUIDField(db_index=True)
    resource = models.ForeignKey(Resource, null=True, blank=True, on_delete=models.CASCADE, related_name="downtimes")
    offering = models.ForeignKey(Offering, null=True, blank=True, on_delete=models.CASCADE, related_name="downtimes")
    reason = models.CharField(max_length=12, choices=Reason.choices)
    note = models.CharField(max_length=300, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    recorded_by = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start"]
        indexes = [models.Index(fields=["tenant_id", "location_id", "start"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(resource__isnull=True) | models.Q(offering__isnull=True),
                name="downtime_one_target",
            ),
            models.CheckConstraint(
                condition=models.Q(end__isnull=True) | models.Q(end__gt=models.F("start")),
                name="downtime_ends_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reason} {self.start:%Y-%m-%d %H:%M}"

    @property
    def target(self) -> str:
        return "resource" if self.resource_id else "offering" if self.offering_id else "location"
