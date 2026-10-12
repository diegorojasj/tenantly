from __future__ import annotations

import uuid

from django.db import models


class NeverDeleted(models.QuerySet):
    """Admins and their audit trail are kept for good: bulk deletes are refused too."""

    def delete(self) -> tuple[int, dict[str, int]]:
        msg = f"{self.model.__name__} rows are never deleted"
        raise PermissionError(msg)


class PlatformAdmin(models.Model):
    """Tenantly staff who open the admin console. Not a `User`: no business, no tenant token.

    Access is a window opened from the server (`manage.py activate_admin`) that closes by
    itself at `active_until`. Rows are never deleted, only blocked, so the audit trail always
    names a real admin.
    """

    class Status(models.TextChoices):
        DORMANT = "dormant"
        ACTIVE = "active"
        BLOCKED = "blocked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=120)
    password_hash = models.CharField(max_length=256)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DORMANT)
    active_until = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    # Who opened the current window: the server account that ran the command.
    activated_by = models.CharField(max_length=120, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = NeverDeleted.as_manager()

    def __str__(self) -> str:
        return self.email

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:  # noqa: ARG002
        msg = "Tenantly admins are never deleted: block them instead"
        raise PermissionError(msg)


class AdminAuditEvent(models.Model):
    """Append-only: everything an admin does, and everything done to an admin."""

    class Kind(models.TextChoices):
        CREATED = "created"
        ACTIVATED = "activated"
        LOGIN = "login"
        LOGIN_DENIED = "login_denied"
        EXPIRED = "expired"
        BLOCKED = "blocked"
        ACTION = "action"

    # Empty only for a sign-in attempt with an email no admin has.
    admin = models.ForeignKey(PlatformAdmin, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    # What was done, for `action` (e.g. `owner.status`); why, for the others.
    action = models.CharField(max_length=60, blank=True)
    target_type = models.CharField(max_length=30, blank=True)
    target_id = models.CharField(max_length=254, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip = models.CharField(max_length=64, blank=True)
    at = models.DateTimeField(db_index=True)

    objects = NeverDeleted.as_manager()

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self) -> str:
        return f"{self.kind} {self.action} @ {self.at:%Y-%m-%d %H:%M}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk:
            msg = "Admin audit events are append-only"
            raise PermissionError(msg)
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:  # noqa: ARG002
        msg = "Admin audit events are never deleted"
        raise PermissionError(msg)
