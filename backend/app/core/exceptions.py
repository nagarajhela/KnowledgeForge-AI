from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


class AppError(Exception):
    """Base application exception with deterministic HTTP status and structured error code."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        error_code: str = "bad_request",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details


class AuthenticationError(AppError):
    def __init__(self, message: str = "Authentication failed", error_code: str = "unauthorized") -> None:
        super().__init__(message, status_code=status.HTTP_401_UNAUTHORIZED, error_code=error_code)


class AuthorizationError(AppError):
    def __init__(self, message: str = "Insufficient permissions", error_code: str = "forbidden") -> None:
        super().__init__(message, status_code=status.HTTP_403_FORBIDDEN, error_code=error_code)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", error_code: str = "not_found") -> None:
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND, error_code=error_code)


class ConflictError(AppError):
    def __init__(self, message: str = "Resource conflict", error_code: str = "conflict") -> None:
        super().__init__(message, status_code=status.HTTP_409_CONFLICT, error_code=error_code)


class QuotaExceededError(AppError):
    def __init__(self, message: str = "Plan quota exceeded", details: Any = None) -> None:
        super().__init__(
            message,
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            error_code="quota_exceeded",
            details=details,
        )


class RateLimitExceededError(AppError):
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60) -> None:
        super().__init__(
            message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error_code="rate_limit_exceeded",
            details={"retry_after_seconds": retry_after},
        )


def _error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id_ctx.get(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload("http_error", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_payload("validation_error", "Request validation failed", exc.errors()),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception", extra={"extra_data": {"error_type": type(exc).__name__}})
        message = str(exc) if not settings.is_production else "An unexpected internal error occurred."
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload("internal_server_error", message),
        )
