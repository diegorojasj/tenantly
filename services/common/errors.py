"""One error shape for every service: `{"detail": "...", "code": "..."}`.

`detail` is written for the person using the app; the frontend shows it as-is.
"""

from __future__ import annotations

from http import HTTPStatus


class ApiError(Exception):
    status = HTTPStatus.BAD_REQUEST
    code = "invalid"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvalidError(ApiError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "invalid"


class UnauthenticatedError(ApiError):
    status = HTTPStatus.UNAUTHORIZED
    code = "unauthenticated"


class ForbiddenError(ApiError):
    status = HTTPStatus.FORBIDDEN
    code = "forbidden"


class NotFoundError(ApiError):
    status = HTTPStatus.NOT_FOUND
    code = "not_found"


class ConflictError(ApiError):
    status = HTTPStatus.CONFLICT
    code = "conflict"


class UnavailableError(ApiError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    code = "unavailable"
