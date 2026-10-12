"""Accounts, sessions and workspaces. Authenticated with a session token.

Nothing here creates an account or a business: Tenantly admins create owners and their
businesses (controllers/admin.py), and owners create their team's accounts (controllers/tenant.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ninja import Router
from ninja.security import HttpBearer

from common.schemas import Ok

from ..schemas import InviteCodeIn, LoginIn, TokenIn
from ..services import accounts, tenants

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ..models import User


class SessionAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str) -> User:
        request.session_token = token  # type: ignore[attr-defined]
        return accounts.user_for_token(token)


router = Router(tags=["account"])
session = SessionAuth()


def _user(user: User) -> dict[str, Any]:
    initials = "".join(part[0] for part in user.name.split()[:2]).upper()
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "title": "",
        "initials": initials,
        "restricted": user.status == user.Status.RESTRICTED,
    }


@router.post("/auth/login", auth=None)
def login(request: HttpRequest, body: LoginIn) -> dict[str, Any]:  # noqa: ARG001
    user, token = accounts.login(body.email, body.password, body.invite)
    return {"token": token, "user": _user(user)}


@router.post("/auth/logout", auth=session, response=Ok)
def logout(request: HttpRequest) -> Ok:
    accounts.logout(request.session_token)  # type: ignore[attr-defined]
    return Ok()


@router.get("/me", auth=session)
def me(request: HttpRequest) -> dict[str, Any]:
    return _user(request.auth)


@router.get("/me/workspaces", auth=session)
def my_workspaces(request: HttpRequest) -> list[dict[str, Any]]:
    return tenants.workspaces(request.auth)


@router.post("/me/invites", auth=session)
def accept_invite(request: HttpRequest, body: InviteCodeIn) -> dict[str, bool]:
    """Claim an invite while already signed in (the code must match this account's email)."""
    return {"joined": accounts.claim_invite(request.auth, body.invite)}


@router.get("/templates", auth=None)
def list_templates(request: HttpRequest) -> list[dict[str, Any]]:  # noqa: ARG001
    return tenants.templates()


@router.post("/tenants/{slug}/token", auth=session)
def enter_tenant(request: HttpRequest, slug: str, body: TokenIn) -> dict[str, Any]:
    token, context = tenants.enter(request.auth, slug, body.scope)
    return {"token": token, "context": context}
