"""WebSocket 广播（FastAPI 原生，无额外依赖）。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)

_clients: set[WebSocket] = set()
_lock = asyncio.Lock()


async def ws_register(ws: WebSocket) -> None:
    await ws.accept()
    async with _lock:
        _clients.add(ws)


async def ws_unregister(ws: WebSocket) -> None:
    async with _lock:
        _clients.discard(ws)


async def ws_broadcast(topic: str, payload: dict[str, Any]) -> int:
    msg = json.dumps({"topic": topic, "data": payload}, ensure_ascii=False)
    dead: list[WebSocket] = []
    sent = 0
    async with _lock:
        clients = list(_clients)
    for ws in clients:
        try:
            await ws.send_text(msg)
            sent += 1
        except Exception:
            dead.append(ws)
    if dead:
        async with _lock:
            for ws in dead:
                _clients.discard(ws)
    return sent
