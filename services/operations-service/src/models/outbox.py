from __future__ import annotations

from django.db import models


class MoneyEvent(models.Model):
    """A charge or refund for billing, written in the same transaction as the change that causes it.

    Billing is another service, so calling it mid-transaction could leave money
    behind when the change rolls back (or the reverse). Events are sent after
    commit, in order, with their id as the idempotency key; whatever fails stays
    pending and `manage.py send_money` retries it.
    """

    tenant_id = models.UUIDField(db_index=True)
    path = models.CharField(max_length=120)
    body = models.JSONField()
    attempts = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.path} #{self.id}"
