"""Service-to-service calls.

`/internal/*` routes accept only the shared `X-Internal-Token`; the proxy never
forwards them from outside. `call` is the only way a service talks to another,
so timeouts and error translation live in one place.
"""

from __future__ import annotations

import hmac
import logging
from typing import TYPE_CHECKING, Any

import httpx
from django.conf import settings
from django.utils.translation import gettext as _
from ninja.security import APIKeyHeader

from .errors import ApiError, ConflictError, ForbiddenError, InvalidError, NotFoundError, UnavailableError
from .i18n import language

if TYPE_CHECKING:
    from django.http import HttpRequest

    from .auth import TenantClaims

log = logging.getLogger(__name__)

HEADER = "X-Internal-Token"
TIMEOUT_SECONDS = 5.0

# Tests swap in an httpx.MockTransport; production uses the network.
_transport: httpx.BaseTransport | None = None


def use_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport  # noqa: PLW0603
    _transport = transport


def _token() -> str:
    token = getattr(settings, "INTERNAL_TOKEN", "")
    if not token:
        msg = "INTERNAL_TOKEN is not set"
        raise RuntimeError(msg)
    return token


class InternalAuth(APIKeyHeader):
    param_name = HEADER

    def authenticate(self, request: HttpRequest, key: str | None) -> bool | None:  # noqa: ARG002
        if key and hmac.compare_digest(key, _token()):
            return True
        return None


_ERRORS: dict[int, type[ApiError]] = {403: ForbiddenError, 404: NotFoundError, 409: ConflictError, 422: InvalidError}


def call(service: str, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None) -> Any:
    """Call another service's internal API. Its user-facing errors pass through unchanged."""
    base = getattr(settings, f"{service.upper()}_URL", "")
    if not base:
        msg = f"{service.upper()}_URL is not set"
        raise RuntimeError(msg)
    try:
        with httpx.Client(base_url=base, timeout=TIMEOUT_SECONDS, transport=_transport) as client:
            # The caller's language travels on, so errors passed through read in it.
            headers = {HEADER: _token(), "Accept-Language": language()}
            response = client.request(method, path, json=json, params=params, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("internal call %s %s %s failed: %s", service, method, path, exc)
        msg = _("The %(service)s service is unavailable — try again in a moment") % {"service": service}
        raise UnavailableError(msg) from exc
    try:
        data = response.json() if response.content else None
    except ValueError:
        # A gateway's HTML error page, not one of our JSON answers.
        data = None
        if response.status_code < 400:  # noqa: PLR2004
            msg = _("The %(service)s service sent an unreadable answer") % {"service": service}
            raise UnavailableError(msg) from None
    if response.status_code >= 400:  # noqa: PLR2004
        failed = _("Request failed")
        detail = data.get("detail", failed) if isinstance(data, dict) else failed
        raise _ERRORS.get(response.status_code, UnavailableError)(str(detail))
    return data


def audit(claims: TenantClaims, action: str, category: str, target: str, scope_id: str | None) -> None:
    """Append to the tenant's tamper-evident trail (owned by identity). Raises if it can't be recorded."""
    call(
        "identity",
        "POST",
        "/internal/audit",
        json={
            "tenantId": claims.tenant_id,
            "actorId": claims.user_id,
            "actorName": claims.user_name,
            "action": action,
            "category": category,
            "target": target,
            "scopeId": scope_id,
            "scopeName": claims.name_of(scope_id),
        },
    )
