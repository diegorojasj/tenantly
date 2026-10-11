from __future__ import annotations

from django.db import models

from .tenant import Tenant


class AuditEvent(models.Model):
    """One link of a tenant's hash chain. Rows are only ever appended."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="audit_events")
    seq = models.PositiveIntegerField()
    at = models.DateTimeField()
    actor_id = models.CharField(max_length=64)
    actor_name = models.CharField(max_length=120)
    action = models.CharField(max_length=60)
    category = models.CharField(max_length=20)
    target = models.CharField(max_length=300)
    scope_id = models.CharField(max_length=64, null=True, blank=True)
    scope_name = models.CharField(max_length=120, blank=True)
    ip = models.CharField(max_length=64, blank=True)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)

    class Meta:
        ordering = ["seq"]
        constraints = [models.UniqueConstraint(fields=["tenant", "seq"], name="audit_seq_per_tenant")]

    def __str__(self) -> str:
        return f"{self.tenant_id}#{self.seq} {self.action}"
