#!/usr/bin/env python3
"""VPS ADB Edge Agent：零手装，轮询 edge_brain → 左机发图 / 右机 open。"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("BOT_ROOT", str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [edge-adb] %(message)s")
log = logging.getLogger("edge_adb")

BRAIN = os.environ.get("EDGE_BRAIN_URL", "http://127.0.0.1:8790").rstrip("/")
LEFT = os.environ.get("EDGE_LEFT_SERIAL", "127.0.0.1:52840")
RIGHT = os.environ.get("EDGE_RIGHT_SERIAL", "127.0.0.1:58433")
PANEL = os.environ.get("BOT_PANEL_URL", "http://127.0.0.1:3000").rstrip("/")
_DONE: set[int] = set()


def _headers() -> dict[str, str]:
    from edge_brain.jwt_auth import authorization_header

    return authorization_header()


def brain_get(path: str) -> dict:
    req = urllib.request.Request(f"{BRAIN}{path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def brain_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BRAIN}{path}",
        data=data,
        method="POST",
        headers={**_headers(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_bots() -> tuple[dict, dict]:
    req = urllib.request.Request(f"{PANEL}/api/bots", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        bots = json.loads(resp.read().decode("utf-8"))
    by_id = {str(b.get("id")): b for b in bots if isinstance(b, dict)}
    left = by_id.get("bot-3") or {"id": "bot-3", "associatedGroup": ""}
    right = by_id.get("bot-4") or {"id": "bot-4", "associatedGroup": ""}
    return left, right


def decode_bundle_images(bundle: dict) -> list[str]:
    paths: list[str] = []
    td = Path(tempfile.mkdtemp(prefix="edge_bundle_"))
    for img in bundle.get("images") or []:
        kind = str(img.get("kind") or "img")
        raw = base64.standard_b64decode(img.get("b64") or "")
        p = td / f"bot_{bundle['period']}_{kind}.png"
        p.write_bytes(raw)
        paths.append(str(p))
    return paths


def run_left_once(d: object, left_bot: dict, period: int) -> bool:
    if period in _DONE:
        return True
    try:
        bundle = brain_get(f"/settle-bundle?period={period}")
    except urllib.error.HTTPError as ex:
        log.debug("bundle skip rid=%s: %s", period, ex)
        return False
    paths = decode_bundle_images(bundle)
    if not paths:
        return False
    settings: dict = {}
    snap = d.ui_snapshot(LEFT, chat=True, channel="edge-adb")
    sy = snap.inbar_send or snap.keyboard_send
    ok = d.send_chat_images_batch(
        LEFT, left_bot, paths, snap.input_xy, sy, settings,
        group_ok=True, settle_rid=period,
    )
    brain_post("/settle-done", {"period": period, "images_ok": bool(ok), "device": "edge-adb-left"})
    if ok:
        _DONE.add(period)
        log.info("左机 edge-adb 发图 OK rid=%s", period)
    else:
        log.warning("左机 edge-adb 发图 FAIL rid=%s", period)
    return ok


def run_right_open(d: object, right_bot: dict) -> bool:
    try:
        job = brain_get("/edge/open-job")
    except Exception as ex:
        log.debug("open-job skip: %s", ex)
        return False
    gates = job.get("gates") or {}
    if not gates.get("open"):
        return False
    open_rid = int(gates.get("open_rid") or 0)
    if open_rid <= 0:
        return False
    settings: dict = {}
    snap = d.ui_snapshot(RIGHT, chat=False, channel="edge-adb")
    sy = d.listener_pinned_send_xy(settings, snap) if hasattr(d, "listener_pinned_send_xy") else (
        snap.inbar_send or snap.keyboard_send
    )
    text = d.build_open_announce_text(open_rid, settings)
    ok = d.send_chat_reply(
        RIGHT, right_bot, text, snap.input_xy, sy, settings, skip_fast=True, group_ok=True,
    )
    if ok:
        log.info("右机 edge-adb open OK rid=%s", open_rid)
        brain_post("/settle-done", {"period": open_rid - 1, "images_ok": True, "device": "edge-adb-open-ack"})
    return ok


def main() -> int:
    try:
        from bot_ops.runtime import apply_bot_start_env
    except ImportError:
        apply_bot_start_env = lambda _r: None  # type: ignore
    apply_bot_start_env(ROOT)
    import bot_55chat_daemon as d  # noqa: WPS433

    os.environ["BOT_CLICKER_SEND_IMAGES"] = "1"
    left_bot, right_bot = load_bots()
    log.info("edge-adb 启动 L=%s R=%s brain=%s", LEFT, RIGHT, BRAIN)
    while True:
        try:
            tl = brain_get("/edge/timeline")
            pending = int(tl.get("rid", 0)) - 1
            if pending > 0 and pending not in _DONE:
                run_left_once(d, left_bot, pending)
            run_right_open(d, right_bot)
        except Exception as ex:
            log.warning("loop: %s", ex)
        time.sleep(float(os.environ.get("EDGE_ADB_LOOP_SEC", "0.8") or 0.8))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
