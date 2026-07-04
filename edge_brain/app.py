"""FastAPI 应用入口。"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from edge_brain import pubsub
from edge_brain.errors import register_exception_handlers
from edge_brain.jwt_auth import verify_bearer, verify_token
from edge_brain.state import consume_open_job, get_gates, mark_settle_done
from w49_core import draw as draw_mod
from w49_core.timing import build_timeline
from w49_render.png_bundle import build_settle_images, fetch_trade_flow

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="W49 Edge Brain", version="0.1.0")
register_exception_handlers(app)


def _auth(authorization: str | None = Header(default=None)) -> None:
    verify_bearer(authorization)


def _ws_auth(token: str) -> None:
    from edge_brain.jwt_auth import auth_disabled

    if auth_disabled():
        return
    verify_token(token)


class SettleDoneBody(BaseModel):
    period: int = Field(gt=0)
    images_ok: bool = True
    device: str = ""


class EdgeEventBody(BaseModel):
    device: str = "right"
    nick: str = ""
    cmd: str = ""
    ts: int = 0


def _build_open_text(open_rid: int) -> str:
    tpl_path = ROOT / "config" / "55m-knowledge" / "announce-templates.json"
    tpl = (
        "【{round_id}期】 新的一局开始\n"
        "（{round_time}）"
    )
    if tpl_path.is_file():
        data = json.loads(tpl_path.read_text(encoding="utf-8"))
        tpl = str((data.get("templates") or {}).get("open", {}).get("template") or tpl)
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    round_time = now.strftime("%Y-%m-%d %H:%M:%S")
    return tpl.format(round_id=open_rid, round_time=round_time)


@app.get("/health")
def health() -> dict[str, str]:
    return {"ok": "true", "service": "edge_brain"}


@app.get("/edge/timeline", dependencies=[Depends(_auth)])
def edge_timeline() -> dict[str, Any]:
    tl = build_timeline()
    tl["gates"] = get_gates()
    return tl


@app.get("/settle-bundle", dependencies=[Depends(_auth)])
def settle_bundle(period: int) -> dict[str, Any]:
    data = draw_mod.fetch_28run_recent()
    d = draw_mod.find_draw_for_round(period, data)
    if not d:
        raise HTTPException(status_code=404, detail=f"draw not found rid={period}")
    flow = fetch_trade_flow(period)
    images = build_settle_images(period, d, flow)
    tl = build_timeline()
    return {
        "period": period,
        "draw": d,
        "trade_flow": flow,
        "images": images,
        "open_rid": max(int(tl.get("open_rid") or 0), period + 1),
        "server_ts": int(time.time() * 1000),
    }


@app.post("/settle-done", dependencies=[Depends(_auth)])
async def settle_done(body: SettleDoneBody) -> dict[str, Any]:
    open_rid = body.period + 1
    st = mark_settle_done(body.period, images_ok=body.images_ok, open_rid=open_rid)
    payload = {"period": body.period, "images_ok": body.images_ok, "gates": st.get("gates")}
    await pubsub.ws_broadcast("settle_done", payload)
    if body.images_ok:
        await pubsub.ws_broadcast("open_gate", {"open_rid": open_rid, "settled": body.period})
    return {"ok": True, "gates": st.get("gates")}


@app.get("/edge/open-job", dependencies=[Depends(_auth)])
def edge_open_job(period: int | None = None) -> dict[str, Any]:
    if period and period > 0:
        job = consume_open_job(period)
        return {"job": job}
    gates = get_gates()
    open_rid = int(gates.get("open_rid") or 0)
    open_text = _build_open_text(open_rid) if gates.get("open") and open_rid > 0 else ""
    return {"gates": gates, "job": None, "open_text": open_text}


@app.post("/edge/event", dependencies=[Depends(_auth)])
async def edge_event(body: EdgeEventBody) -> dict[str, Any]:
    await pubsub.ws_broadcast("edge_event", body.model_dump())
    return {"ok": True, "queued": False, "echo": body.cmd}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = ""):
    try:
        _ws_auth(token)
    except HTTPException:
        await ws.close(code=4401)
        return
    await pubsub.ws_register(ws)
    try:
        await ws.send_json({"topic": "hello", "data": build_timeline()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.ws_unregister(ws)
