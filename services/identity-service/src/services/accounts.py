"""Accounts and browser sessions.

There is no public sign-up: a Tenantly admin creates each owner's account (services/admin.py)
and an owner creates their team's (services/team.py), both through `create_account`.
Session tokens are random and only their SHA-256 is stored, so a database
leak can't be replayed. Signing in with an invite code also claims the
invite, provided it was sent to that email address.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from common.errors import ConflictError, InvalidError, UnauthenticatedError

from ..models import Membership, Session, User

MIN_PASSWORD = 8
MIN_NAME = 2


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _normalize(email: str) -> str:
    return email.strip().lower()


def open_session(user: User) -> str:
    token = secrets.token_urlsafe(32)
    Session.objects.create(
        user=user,
        token_hash=_hash(token),
        expires_at=timezone.now() + timedelta(days=settings.SESSION_TTL_DAYS),
    )
    return token


def invite_code() -> tuple[str, str]:
    """A fresh one-time invite code and the hash that is stored for it."""
    code = secrets.token_urlsafe(24)
    return code, _hash(code)


def claim_invite(user: User, code: str | None) -> bool:
    """Turn the invite behind `code` into an active membership, if it was sent to this user's email.

    The code proves the person was handed the invite; the email match stops a
    leaked code from being redeemed by someone else.
    """
    if not code:
        return False
    return bool(
        Membership.objects.filter(
            invite_hash=_hash(code), email=user.email, user__isnull=True, status=Membership.Status.INVITED
        ).update(user=user, status=Membership.Status.ACTIVE, invite_hash=None)
    )


def create_account(name: str, email: str, password: str, created_by: User | None = None) -> User:
    """A new account with the password its creator chose; no session is opened for it.

    `created_by` is the owner a team account belongs to; None for an owner (a Tenantly admin's).
    """
    name = name.strip()
    email = _normalize(email)
    if len(name) < MIN_NAME:
        msg = _("Enter their name")
        raise InvalidError(msg)
    if "@" not in email:
        msg = _("Enter a valid email address")
        raise InvalidError(msg)
    if len(password) < MIN_PASSWORD:
        msg = _("Use at least %(n)s characters for the password") % {"n": MIN_PASSWORD}
        raise InvalidError(msg)
    if User.objects.filter(email=email).exists():
        msg = _("An account with this email already exists")
        raise ConflictError(msg)
    return User.objects.create(name=name, email=email, password_hash=make_password(password), created_by=created_by)


def _refuse_suspended(user: User) -> None:
    if user.status == User.Status.SUSPENDED:
        msg = _("This account is suspended. Contact Tenantly support to restore it")
        raise UnauthenticatedError(msg)


@transaction.atomic
def login(email: str, password: str, invite: str | None = None) -> tuple[User, str]:
    user = User.objects.filter(email=_normalize(email)).first()
    if not user or not check_password(password, user.password_hash):
        msg = _("Email or password is incorrect")
        raise UnauthenticatedError(msg)
    # Only after the password matched, so suspension never tells a stranger the account exists.
    _refuse_suspended(user)
    claim_invite(user, invite)
    return user, open_session(user)


def logout(token: str) -> None:
    Session.objects.filter(token_hash=_hash(token)).delete()


def user_for_token(token: str) -> User:
    session = (
        Session.objects.select_related("user").filter(token_hash=_hash(token), expires_at__gt=timezone.now()).first()
    )
    if not session:
        msg = _("Sign in to continue")
        raise UnauthenticatedError(msg)
    _refuse_suspended(session.user)
    return session.user
