"""The NinjaAPI every service starts from: one error shape and a health probe."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.utils.translation import gettext as _
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, ValidationError

from .errors import ApiError

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


def create_api(title: str) -> NinjaAPI:
    api = NinjaAPI(title=title, version="1.0.0", docs_url="/docs" if settings.DEBUG else None)

    @api.exception_handler(ApiError)
    def api_error(request: HttpRequest, exc: ApiError) -> HttpResponse:
        return api.create_response(request, {"detail": exc.detail, "code": exc.code}, status=exc.status)

    @api.exception_handler(AuthenticationError)
    def auth_error(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:  # noqa: ARG001
        return api.create_response(request, {"detail": _("Sign in to continue"), "code": "unauthenticated"}, status=401)

    @api.exception_handler(ValidationError)
    def validation_error(request: HttpRequest, exc: ValidationError) -> HttpResponse:
        first = exc.errors[0] if exc.errors else {}
        where = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        detail = f"{where}: {first.get('msg') or _('invalid value')}"
        return api.create_response(request, {"detail": detail, "code": "invalid"}, status=422)

    @api.get("/health", auth=None, tags=["health"])
    def health(request: HttpRequest) -> dict[str, str]:  # noqa: ARG001
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return api
