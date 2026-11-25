"""Domain errors and their HTTP mapping."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(DomainError):
    """Also used for "exists but not yours", so existence across tenants isn't revealed."""

    status_code = 404
    code = "not_found"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(DomainError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMediaType(DomainError):
    status_code = 415
    code = "unsupported_media_type"


class Unprocessable(DomainError):
    """Well-formed request that breaks a domain rule (e.g. an unknown jurisdiction)."""

    status_code = 422
    code = "unprocessable"


class Unauthenticated(DomainError):
    status_code = 401
    code = "unauthenticated"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, Unauthenticated) else None
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    **({"details": exc.details} if exc.details else {}),
                }
            },
            headers=headers,
        )
