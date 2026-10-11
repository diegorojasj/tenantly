from __future__ import annotations

from django.db import models


class PolicyOverride(models.Model):
    """A rule set at one node of the tree; it applies to everything beneath it."""

    tenant_id = models.UUIDField(db_index=True)
    node_id = models.UUIDField()
    key = models.CharField(max_length=40)
    value = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["node_id", "key"], name="one_override_per_node_key")]

    def __str__(self) -> str:
        return f"{self.node_id}:{self.key}={self.value}"
