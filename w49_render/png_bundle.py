"""生成 settle-bundle 三图 PNG（VPS board_capture 优先，否则 Pillow 占位）。"""
from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

KINDS = ("pc28", "mark6", "flow")


def _pillow_placeholder(kind: str, period: int, draw: dict[str, Any], flow: dict[str, Any]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    w, h = 720, 400
    img = Image.new("RGB", (w, h), (18, 22, 32))
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
        font_s = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
        font_s = font
    title = {"pc28": "PC28结果", "mark6": "六合走势图", "flow": "最新交易流水"}[kind]
    dr.text((24, 20), f"{title}  rid={period}", fill=(240, 240, 255), font=font)
    if kind == "pc28":
        body = f"{draw.get('n1')}+{draw.get('n2')}+{draw.get('n3')}={draw.get('final_result')}"
    elif kind == "mark6":
        body = f"opentime {draw.get('opentime', '')}"
    else:
        rows = flow.get("rows") or flow.get("bets") or []
        body = f"rows={len(rows)} mock={bool(flow.get('mock'))}"
    dr.text((24, 70), body[:80], fill=(200, 210, 220), font=font_s)
    dr.rectangle([12, 12, w - 12, h - 12], outline=(80, 120, 200), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _board_capture_paths(period: int, draw: dict[str, Any]) -> list[str] | None:
    try:
        from board_capture import (
            render_mark6_board_png,
            render_pc28_board_png,
            render_trade_flow_png,
        )
    except ImportError:
        return None
    try:
        import bot_55chat_daemon as d  # noqa: WPS433

        boards = d.fetch_panel_draw_boards()
        flow = d.fetch_panel_trade_flow(period)
        return [
            render_pc28_board_png(boards, round_id=period),
            render_mark6_board_png(boards, round_id=period),
            render_trade_flow_png(flow, round_id=period),
        ]
    except Exception as ex:
        log.warning("board_capture 失败 rid=%s: %s", period, ex)
        return None


def fetch_trade_flow(period: int) -> dict[str, Any]:
    panel = os.environ.get("BOT_PANEL_URL", "http://127.0.0.1:3000").rstrip("/")
    try:
        import urllib.request

        url = f"{panel}/api/trade-flow?period={period}&botIds=bot-3,bot-4"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=float(os.environ.get("BOT_PANEL_HTTP_TIMEOUT_SEC", "3"))) as resp:
            data = __import__("json").loads(resp.read().decode("utf-8"))
        if isinstance(data, dict):
            return data
    except Exception as ex:
        log.debug("trade-flow panel skip: %s", ex)
    return {"period": period, "rows": [], "mock": True}


def build_settle_images(
    period: int,
    draw: dict[str, Any],
    flow: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    flow = flow if flow is not None else fetch_trade_flow(period)
    paths = _board_capture_paths(period, draw)
    out: list[dict[str, Any]] = []
    if paths and len(paths) == 3:
        for kind, p in zip(KINDS, paths):
            raw = Path(p).read_bytes()
            out.append({
                "kind": kind,
                "mime": "image/png",
                "b64": base64.standard_b64encode(raw).decode("ascii"),
                "source": "board_capture",
            })
        return out
    for kind in KINDS:
        raw = _pillow_placeholder(kind, period, draw, flow)
        out.append({
            "kind": kind,
            "mime": "image/png",
            "b64": base64.standard_b64encode(raw).decode("ascii"),
            "source": "pillow_fallback",
        })
    return out
