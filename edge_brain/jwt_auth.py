"""Edge Brain HTTP/WS 鉴权适配层（基于 bot_ops.auth.jwt）。"""
from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException

from bot_ops.auth.jwt import (
    JWTAuthError,
    decode_token,
    encode_token,
)

JWT_AUDIENCE = "w49-edge-brain"
DEFAULT_TTL_SEC = 365 * 24 * 3600


def auth_disabled() -> bool:
    return os.environ.get("EDGE_BRAIN_AUTH_DISABLE", "").lower() in ("1", "true", "yes")


def mint_service_token(
    *,
    sub: str = "edge-service",
    ttl_sec: int = DEFAULT_TTL_SEC,
    extra: dict[str, Any] | None = None,
) -> str:
    return encode_token(
        sub=sub,
        audience=JWT_AUDIENCE,
        ttl_sec=ttl_sec,
        extra=extra,
    )


def verify_token(token: str) -> dict[str, Any]:
    if auth_disabled():
        return {}
    try:
        return decode_token(token, audience=JWT_AUDIENCE)
    except JWTAuthError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc


def verify_bearer(authorization: str | None) -> dict[str, Any]:
    if auth_disabled():
        return {}
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    return verify_token(authorization[7:].strip())


def service_jwt_from_env() -> str:
    """客户端：优先读预签发 JWT，否则用 secret 现场 mint（仅 VPS 侧）。"""
    for key in ("EDGE_BRAIN_JWT", "BOT_EDGE_BRAIN_JWT"):
        raw = os.environ.get(key, "").strip()
        if raw and raw.count(".") == 2:
            return raw
    if os.environ.get("EDGE_BRAIN_JWT_SECRET", "").strip() or os.environ.get("JWT_SECRET", "").strip():
        return mint_service_token()
    raise RuntimeError("Set EDGE_BRAIN_JWT (pre-issued) or EDGE_BRAIN_JWT_SECRET (mint)")


def authorization_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {service_jwt_from_env()}", "Accept": "application/json"}


__all__ = [
    "auth_disabled",
    "authorization_header",
    "decode_token",
    "encode_token",
    "mint_service_token",
    "service_jwt_from_env",
    "verify_bearer",
    "verify_token",
]
