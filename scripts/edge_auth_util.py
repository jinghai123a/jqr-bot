"""Edge Brain 客户端鉴权头（脚本共用）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_ops.auth import encode_token, verify_token  # noqa: E402


def mint_and_export(ttl_days: int = 365) -> str:
    token = encode_token(sub="edge-service", ttl_sec=max(3600, ttl_days * 86400))
    os.environ["EDGE_BRAIN_JWT"] = token
    return token


def ensure_jwt_env() -> str:
    from edge_brain.jwt_auth import service_jwt_from_env

    return service_jwt_from_env()
