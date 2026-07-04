"""28.run 开奖拉取（urllib，无 fcntl 依赖）。"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any

DRAW_API_URL = os.environ.get(
    "BOT_DRAW_API_URL", "https://28.run/api/lottery/recent/6",
)
DRAW_FETCH_INTERVAL = max(0.35, float(os.environ.get("BOT_DRAW_FETCH_SEC", "0.5") or 0.5))

_CACHE: tuple[float, dict[str, Any]] | None = None


def fetch_28run_recent(*, force: bool = False) -> dict[str, Any] | None:
    global _CACHE
    now = time.time()
    if not force and _CACHE and now - _CACHE[0] < DRAW_FETCH_INTERVAL:
        return _CACHE[1]
    try:
        req = urllib.request.Request(
            DRAW_API_URL,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://28.run/",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict):
            _CACHE = (now, data)
            return data
    except Exception:
        return _CACHE[1] if _CACHE else None
    return None


def normalize_draw_row(row: dict[str, Any]) -> dict[str, Any]:
    n1 = int(row.get("number1", 0))
    n2 = int(row.get("number2", 0))
    n3 = int(row.get("number3", 0))
    final_result = int(row.get("final_result", n1 + n2 + n3))
    return {
        "round_id": int(row.get("expect", 0)),
        "n1": n1,
        "n2": n2,
        "n3": n3,
        "final_result": final_result,
        "opentime": str(row.get("opentime") or ""),
    }


def find_draw_in_data(data: dict[str, Any] | None, round_id: int) -> dict[str, Any] | None:
    if not data:
        return None
    for row in data.get("recent_results") or []:
        try:
            if int(row.get("expect", 0)) == int(round_id):
                return normalize_draw_row(row)
        except (TypeError, ValueError):
            continue
    return None


def find_draw_for_round(round_id: int, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if data is not None:
        hit = find_draw_in_data(data, round_id)
        if hit:
            return hit
    payload = data if data is not None else fetch_28run_recent()
    if not payload:
        return None
    return find_draw_in_data(payload, round_id)


def latest_drawn_round_id(data: dict[str, Any] | None) -> int:
    if not data:
        return 0
    rows = data.get("recent_results") or []
    if not rows:
        return 0
    try:
        return int(rows[-1].get("expect", 0))
    except (TypeError, ValueError):
        return 0
