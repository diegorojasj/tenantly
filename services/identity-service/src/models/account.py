from __future__ import annotations

import uuid

from django.db import models


class User(models.Model):
    """A person. One account can belong to many businesses (tenants). Never Tenantly staff (`PlatformAdmin`).

    Nobody signs themselves up: a Tenantly admin creates each business owner's account (with
    their first business), and an owner creates their team's accounts. A team account rides on
    the businesses it belongs to, so on the owner's Tenantly subscription, never one of its own.
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        RESTRICTED = "restricted"
        SUSPENDED = "suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=120)
    password_hash = models.CharField(max_length=256)
    # Set by a Tenantly admin. Restricted: signs in, reads, changes nothing. Suspended: no sign-in, no session.
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    # The owner who created this team account; null for owners (created by a Tenantly admin).
    created_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="team_accounts"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.email


class Session(models.Model):
    """A signed-in browser. Only the SHA-256 of the token is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"session {self.id}"
