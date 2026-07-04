"""Edge Brain 统一 JSON 错误响应（无项目级规范时的默认信封）。"""
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def error_envelope(message: str) -> dict[str, object]:
    return {"success": False, "error": message}


def error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_envelope(message))


def _detail_to_message(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(x) for x in item.get("loc", ()))
                msg = str(item.get("msg") or item)
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        return "; ".join(parts) or "request error"
    return str(detail)


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return error_response(exc.status_code, _detail_to_message(exc.detail))


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(422, _detail_to_message(exc.errors()))


def register_exception_handlers(app: object) -> None:
    add = getattr(app, "add_exception_handler", None)
    if add is None:
        return
    add(HTTPException, http_exception_handler)
    add(RequestValidationError, validation_exception_handler)
