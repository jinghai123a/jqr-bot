"""JWT 签发与校验（PyJWT / HS256）。密钥只从环境变量读取。"""
from __future__ import annotations

import os
import time
from typing import Any

import jwt

DEFAULT_ALGORITHM = "HS256"
DEFAULT_AUDIENCE = "w49-edge-brain"
DEFAULT_TTL_SEC = 365 * 24 * 3600

# 按优先级读取；禁止在代码中写死 secret
_SECRET_ENV_KEYS = ("EDGE_BRAIN_JWT_SECRET", "JWT_SECRET")


class JWTAuthError(Exception):
    """鉴权失败基类。"""


class JWTSecretMissingError(JWTAuthError):
    """未配置 JWT 密钥。"""


class JWTAlgorithmError(JWTAuthError):
    """算法不允许。"""


def jwt_secret_from_env() -> str:
    for key in _SECRET_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    raise JWTSecretMissingError(
        f"JWT secret missing; set one of: {', '.join(_SECRET_ENV_KEYS)}"
    )


def encode_token(
    *,
    sub: str = "service",
    audience: str = DEFAULT_AUDIENCE,
    ttl_sec: int = DEFAULT_TTL_SEC,
    extra: dict[str, Any] | None = None,
    algorithm: str = DEFAULT_ALGORITHM,
) -> str:
    """生成 JWT（Sign / Encode）。"""
    if algorithm != DEFAULT_ALGORITHM:
        raise JWTAlgorithmError(f"unsupported algorithm: {algorithm}")
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "aud": audience,
        "iat": now,
        "exp": now + max(60, int(ttl_sec)),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, jwt_secret_from_env(), algorithm=algorithm)


def verify_token(
    token: str,
    *,
    audience: str = DEFAULT_AUDIENCE,
    algorithms: tuple[str, ...] = (DEFAULT_ALGORITHM,),
) -> dict[str, Any]:
    """验证 JWT 并返回 payload（Verify）。"""
    if not token or token.count(".") != 2:
        raise JWTAuthError("invalid token format")
    try:
        return jwt.decode(
            token,
            jwt_secret_from_env(),
            algorithms=list(algorithms),
            audience=audience,
        )
    except jwt.PyJWTError as exc:
        raise JWTAuthError("invalid token") from exc


def decode_token(
    token: str,
    *,
    audience: str = DEFAULT_AUDIENCE,
    algorithms: tuple[str, ...] = (DEFAULT_ALGORITHM,),
) -> dict[str, Any]:
    """解码 JWT payload（Decode）；无效 token 抛 JWTAuthError。"""
    return verify_token(token, audience=audience, algorithms=algorithms)
