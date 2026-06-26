from typing import Any

from fastapi import HTTPException, status


class AppError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "APP_ERROR",
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        super().__init__(message)


def error_payload(message: str, code: str = "APP_ERROR", details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"message": message, "code": code, "details": details or {}}


def as_http_error(error: AppError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error_payload(error.message, error.code, error.details))
