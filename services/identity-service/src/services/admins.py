"""Tenantly admins: separate accounts with time-boxed access, and their audit log.

An admin is never a `User` and never deleted. Access is a window opened from the server
(`manage.py create_admin` / `activate_admin`, `ADMIN_WINDOW_MINUTES` long, each with a new
password) and closed by
`block_admin` or by time. Every sign-in and every admin request checks the window here; one
found past its end is flipped to `blocked` on the spot and logged, so nothing depends on the
`expire_admins` sweep. Admin tokens are signed with their own key and audience
(`common.auth.issue_admin`), carry the window they were issued in, and expire with it.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from functools import cache
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from common.auth import AdminClaims, issue_admin, verify_admin
from common.errors import ConflictError, InvalidError, NotFoundError, UnauthenticatedError

from ..models import AdminAuditEvent, PlatformAdmin

if TYPE_CHECKING:
    from django.http import HttpRequest

MIN_PASSWORD = 12
MIN_NAME = 2
LOG_PAGE = 50


@cache
def _dummy_hash() -> str:
    """Checked against for an unknown email, so it costs what a wrong password does."""
    return make_password(secrets.token_urlsafe(16))


def now() -> datetime:
    """The admin clock; tests move it."""
    return timezone.now()


def window_minutes() -> int:
    return int(getattr(settings, "ADMIN_WINDOW_MINUTES", 10))


def _normalize(email: str) -> str:
    return email.strip().lower()


def client_ip(request: HttpRequest | None) -> str:
    """Best effort, for the log: the browser's address the frontend passed on, else the last hop."""
    if request is None:
        return ""
    meta = request.META
    forwarded = meta.get("HTTP_X_CLIENT_IP") or meta.get("HTTP_X_REAL_IP") or meta.get("REMOTE_ADDR") or ""
    return str(forwarded).split(",")[0].strip()[:64]


def record(
    admin: PlatformAdmin | None,
    kind: str,
    *,
    action: str = "",
    target: tuple[str, str] = ("", ""),
    before: Any = None,
    after: Any = None,
    ip: str = "",
) -> AdminAuditEvent:
    return AdminAuditEvent.objects.create(
        admin=admin,
        kind=kind,
        action=action[:60],
        target_type=target[0][:30],
        target_id=str(target[1])[:254],
        before=before,
        after=after,
        ip=ip,
        at=now(),
    )


def state(admin: PlatformAdmin) -> dict[str, Any]:
    """What the log keeps of an admin before and after a change."""
    return {
        "status": admin.status,
        "activeUntil": admin.active_until.isoformat() if admin.active_until else None,
    }


def is_open(admin: PlatformAdmin, at: datetime | None = None) -> bool:
    at = at or now()
    return admin.status == PlatformAdmin.Status.ACTIVE and admin.active_until is not None and at < admin.active_until


def remaining(admin: PlatformAdmin) -> int:
    """Whole seconds left in the window (0 when closed)."""
    if not is_open(admin):
        return 0
    return max(0, int((admin.active_until - now()).total_seconds()))  # type: ignore[operator]


def _expire(admin: PlatformAdmin, ip: str = "") -> None:
    """An active admin past their window becomes blocked, once, and the log says so."""
    with transaction.atomic():
        locked = PlatformAdmin.objects.select_for_update().get(pk=admin.pk)
        if locked.status != PlatformAdmin.Status.ACTIVE or is_open(locked):
            return
        before = state(locked)
        locked.status = PlatformAdmin.Status.BLOCKED
        locked.save(update_fields=["status"])
        record(locked, AdminAuditEvent.Kind.EXPIRED, before=before, after=state(locked), ip=ip)
    admin.status = PlatformAdmin.Status.BLOCKED


def closed_message() -> str:
    # Public text: never says how or where access is reopened.
    return _("Your admin access has ended")


# ------------------------------------------------------- server commands --


def _validate_new(email: str, name: str, password: str | None) -> None:
    if "@" not in email:
        msg = _("Enter a valid email address")
        raise InvalidError(msg)
    if len(name.strip()) < MIN_NAME:
        msg = _("Enter your name")
        raise InvalidError(msg)
    if password is not None and len(password) < MIN_PASSWORD:
        msg = _("Use at least %(n)s characters for your password") % {"n": MIN_PASSWORD}
        raise InvalidError(msg)


def _find(email: str) -> PlatformAdmin:
    admin = PlatformAdmin.objects.select_for_update().filter(email=_normalize(email)).first()
    if not admin:
        msg = _("No Tenantly admin with that email")
        raise NotFoundError(msg)
    return admin


def _open_window(admin: PlatformAdmin, by: str) -> None:
    at = now()
    admin.status = PlatformAdmin.Status.ACTIVE
    # Whole seconds: the window is also what admin tokens carry.
    admin.activated_at = at.replace(microsecond=0)
    admin.active_until = admin.activated_at + timedelta(minutes=window_minutes())
    admin.activated_by = by[:120]
    admin.save()


@transaction.atomic
def create(
    email: str, name: str, password: str | None, by: str, *, open_window: bool = True
) -> tuple[PlatformAdmin, str | None]:
    """A new admin, its window open unless asked otherwise; returns the password generated for it, if any."""
    email = _normalize(email)
    _validate_new(email, name, password)
    if PlatformAdmin.objects.filter(email=email).exists():
        msg = _("There's already a Tenantly admin with that email: activate it instead")
        raise ConflictError(msg)
    generated = None if password else secrets.token_urlsafe(18)
    admin = PlatformAdmin.objects.create(
        email=email, name=name.strip(), password_hash=make_password(password or generated)
    )
    record(admin, AdminAuditEvent.Kind.CREATED, target=("admin", str(admin.id)), after=state(admin), ip=by)
    if open_window:
        before = state(admin)
        _open_window(admin, by)
        record(admin, AdminAuditEvent.Kind.ACTIVATED, action="new_password", before=before, after=state(admin), ip=by)
    return admin, generated


@transaction.atomic
def activate(email: str, by: str, password: str | None = None) -> tuple[PlatformAdmin, str | None]:
    """A fresh window from now, whatever the admin's status, and always a new password.

    Tokens from earlier windows stay void and so does the old password: the one given here (not
    the current one) or, if left out, a generated one, returned to be shown once.
    """
    admin = _find(email)
    if password is not None:
        _validate_new(admin.email, admin.name, password)
        if check_password(password, admin.password_hash):
            msg = _("Choose a password different from the current one")
            raise InvalidError(msg)
    generated = None if password else secrets.token_urlsafe(18)
    before = state(admin)
    admin.password_hash = make_password(password or generated)
    _open_window(admin, by)
    record(admin, AdminAuditEvent.Kind.ACTIVATED, action="new_password", before=before, after=state(admin), ip=by)
    return admin, generated


@transaction.atomic
def block(email: str, by: str) -> PlatformAdmin:
    """Close the window now. Their tokens die with it."""
    admin = _find(email)
    before = state(admin)
    admin.status = PlatformAdmin.Status.BLOCKED
    if admin.active_until is None or admin.active_until > now():
        admin.active_until = now()
    admin.save(update_fields=["status", "active_until"])
    record(admin, AdminAuditEvent.Kind.BLOCKED, before=before, after=state(admin), ip=by)
    return admin


def expire_overdue() -> int:
    """The sweep: every active admin past their window becomes blocked. Enforcement never waits for it."""
    overdue = PlatformAdmin.objects.filter(status=PlatformAdmin.Status.ACTIVE, active_until__lte=now())
    count = 0
    for admin in overdue:
        _expire(admin, ip="sweep")
        count += 1
    return count


# ------------------------------------------------------- sign-in and auth --


def _token(admin: PlatformAdmin) -> str:
    window = int(admin.activated_at.timestamp()) if admin.activated_at else 0
    return issue_admin(AdminClaims(admin_id=str(admin.id), name=admin.name, window=window), remaining(admin))


def login(email: str, password: str, ip: str = "") -> tuple[PlatformAdmin, str]:
    """A token that lasts what's left of the window. Every refusal is logged, and reads the same."""
    email = _normalize(email)
    admin = PlatformAdmin.objects.filter(email=email).first()
    wrong = _("Email or password is incorrect")
    if not admin:
        check_password(password, _dummy_hash())
        record(None, AdminAuditEvent.Kind.LOGIN_DENIED, action="unknown_email", target=("email", email), ip=ip)
        raise UnauthenticatedError(wrong)
    if not check_password(password, admin.password_hash):
        record(admin, AdminAuditEvent.Kind.LOGIN_DENIED, action="wrong_password", ip=ip)
        raise UnauthenticatedError(wrong)
    if not is_open(admin):
        _expire(admin, ip)
        record(admin, AdminAuditEvent.Kind.LOGIN_DENIED, action="window_closed", after=state(admin), ip=ip)
        raise UnauthenticatedError(closed_message())
    admin.last_login_at = now()
    admin.save(update_fields=["last_login_at"])
    record(admin, AdminAuditEvent.Kind.LOGIN, after=state(admin), ip=ip)
    return admin, _token(admin)


def authenticate(token: str, ip: str = "") -> PlatformAdmin:
    """Every admin request: a valid admin token, from the current window, which is still open."""
    claims = verify_admin(token)
    admin = PlatformAdmin.objects.filter(id=claims.admin_id).first()
    ended = _("Your admin session ended — sign in again")
    if not admin:
        raise UnauthenticatedError(ended)
    if not admin.activated_at or int(admin.activated_at.timestamp()) != claims.window:
        raise UnauthenticatedError(ended)
    if not is_open(admin):
        _expire(admin, ip)
        raise UnauthenticatedError(closed_message())
    return admin


def demand_open(admin: PlatformAdmin) -> None:
    """Checked again right before anything is forwarded to billing."""
    if not is_open(admin):
        _expire(admin)
        raise UnauthenticatedError(closed_message())


def actor(admin: PlatformAdmin) -> dict[str, str]:
    """How an admin signs what billing records and businesses' audit trails: visibly Tenantly."""
    return {"id": f"admin:{admin.id}", "name": f"{admin.name} (Tenantly)"}


def admin_dict(admin: PlatformAdmin) -> dict[str, Any]:
    return {
        "id": str(admin.id),
        "name": admin.name,
        "email": admin.email,
        "activeUntil": admin.active_until.isoformat() if admin.active_until else None,
        "remainingSeconds": remaining(admin),
    }


# ------------------------------------------------------------------ log --


def _event_dict(e: AdminAuditEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "at": e.at.isoformat(),
        "kind": e.kind,
        "action": e.action,
        "admin": {"id": str(e.admin_id), "name": e.admin.name, "email": e.admin.email} if e.admin else None,
        "targetType": e.target_type,
        "targetId": e.target_id,
        "before": e.before,
        "after": e.after,
        "ip": e.ip,
    }


def log(offset: int = 0) -> dict[str, Any]:
    rows = AdminAuditEvent.objects.select_related("admin")
    offset = max(0, offset)
    return {
        "events": [_event_dict(e) for e in rows[offset : offset + LOG_PAGE]],
        "total": rows.count(),
        "offset": offset,
        "limit": LOG_PAGE,
    }
