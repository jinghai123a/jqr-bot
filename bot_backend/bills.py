"""Bill-related backend API helpers."""
from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from .transport import BackendApiTransport


def record_bill(
    transport: BackendApiTransport,
    logger: logging.Logger,
    bot_id: str,
    username: str,
    bill_type: str,
    amount: float,
    balance_after: float,
    detail: str = "",
    customer_code: str = "",
) -> None:
    try:
        transport.request(
            "POST",
            "/api/bills",
            {
                "botId": bot_id,
                "username": username,
                "type": bill_type,
                "amount": round(float(amount), 3),
                "balanceAfter": round(float(balance_after), 3),
                "detail": detail,
                "customerCode": customer_code,
            },
        )
    except Exception as ex:
        logger.warning("账单记录失败: %s", ex)


def fetch_user_bills(
    transport: BackendApiTransport,
    bot_id: str,
    username: str,
    limit: int = 15,
) -> list[dict[str, Any]]:
    try:
        rows = transport.request(
            "GET",
            f"/api/bills?botId={bot_id}&username={urllib.parse.quote(username)}&limit={limit}",
        )
        return rows if isinstance(rows, list) else []
    except Exception:
        return []
