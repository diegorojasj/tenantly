from __future__ import annotations

import uuid

from django.db import models


class Customer(models.Model):
    """Someone the business serves. `fields` holds the template's typed customer fields.

    A customer may belong to an account (a company they are a contact of, a household)
    with a free-text `account_role`. Plans live in `Subscription`, documents in
    `Document`, the things served for them (pets, vehicles…) in `Subject`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    location_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True)
    email = models.CharField(max_length=160, blank=True)
    since = models.DateField()
    fields = models.JSONField(default=dict)
    account = models.ForeignKey(
        "operations.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="contacts"
    )
    account_role = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
