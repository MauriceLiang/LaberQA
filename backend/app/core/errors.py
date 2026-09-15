import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import ErrorCode

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, code: int, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _error_body(code: int, message: str) -> dict[str, Any]:
    return {"code": int(code), "message": message, "data": None}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_body(exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body(ErrorCode.INVALID_REQUEST, "请求参数不合法"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            code = ErrorCode.INVALID_REQUEST
            message = "请求路径不存在"
        else:
            code = (
                ErrorCode.INVALID_REQUEST
                if exc.status_code in (400, 422)
                else ErrorCode.INTERNAL_ERROR
            )
            message = str(exc.detail) if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, message),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled request error",
            exc_info=exc,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return JSONResponse(
            status_code=500,
            content=_error_body(ErrorCode.INTERNAL_ERROR, "服务内部错误"),
        )
