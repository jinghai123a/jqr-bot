"""零信任物理回看：发公告/发图后 OCR+读屏校验，超 API 预算 2s 触发 P0。"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8))
BUBBLE_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
P0_ALERT_FILE = os.environ.get(
    "BOT_P0_ALERT_FILE",
    "/home/bot/55chat-bot/data/p0_physical_alerts.jsonl",
)
PHYSICAL_LAG_BUDGET_SEC = max(0.5, float(os.environ.get("BOT_PHYSICAL_LAG_BUDGET_SEC", "1.0") or 1.0))
OPEN_SNIPPET_P0 = os.environ.get("BOT_PHYSICAL_OPEN_SNIPPET_P0", "1").lower() in (
    "1",
    "true",
    "yes",
)
PHYSICAL_BURN_SCREENSHOT = os.environ.get("BOT_PHYSICAL_BURN_SCREENSHOT", "1").strip() not in (
    "0",
    "false",
    "no",
)


def _ocr_bottom_roi(png_bytes: bytes) -> str:
    """ADB 截图底部 ROI OCR（cv2 可用时）；失败返回空串。"""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return ""
    if not png_bytes or not getattr(cv2, "imdecode", None):
        return ""
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return ""
    h, w = img.shape[:2]
    roi = img[int(h * 0.55) : h, 0:w]
    try:
        import pytesseract  # type: ignore

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        return (pytesseract.image_to_string(gray, lang="chi_sim+eng") or "").strip()
    except Exception:
        return ""


def parse_bubble_clock(text: str, *, ref: datetime | None = None) -> datetime | None:
    """从气泡旁 H:MM[:SS] 解析北京时间（12h 制）。"""
    ref = ref or datetime.now(BEIJING)
    m = BUBBLE_CLOCK_RE.match((text or "").strip())
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    sec = int(m.group(3) or 0)
    if h <= 12 and ref.hour >= 12 and h < 12:
        h += 12
    try:
        return ref.replace(hour=h % 24, minute=mi, second=sec, microsecond=0)
    except ValueError:
        return None


def extract_latest_bubble_time(texts: list[str], *, ref: datetime | None = None) -> datetime | None:
    ref = ref or datetime.now(BEIJING)
    for t in reversed(texts or []):
        dt = parse_bubble_clock(t, ref=ref)
        if dt:
            return dt
    return None


def physical_feedback_check(
    serial: str,
    *,
    api_deadline: datetime,
    expected_snippet: str,
    kind: str = "announce",
    adb_screencap_fn: Any = None,
    ui_texts_fn: Any = None,
) -> dict[str, Any]:
    """
    发完后强制回看：UI 树 + 截图 OCR。
    若屏幕气泡时间比 API 截止时间晚超过预算 → P0。
    """
    t0 = time.perf_counter()
    texts: list[str] = []
    ocr_text = ""
    png_path = ""
    png_bytes: bytes | None = None
    try:
        if ui_texts_fn:
            texts = list(ui_texts_fn(serial) or [])
        if adb_screencap_fn:
            png_bytes = adb_screencap_fn(serial)
            if png_bytes:
                ocr_text = _ocr_bottom_roi(png_bytes)
                if ocr_text:
                    texts = texts + [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
                if not PHYSICAL_BURN_SCREENSHOT:
                    os.makedirs(
                        os.environ.get(
                            "BOT_PHYSICAL_ARTIFACT_DIR",
                            "/home/bot/55chat-bot/artifacts/physical-feedback",
                        ),
                        exist_ok=True,
                    )
                    ts = int(time.time())
                    png_path = os.path.join(
                        os.environ.get(
                            "BOT_PHYSICAL_ARTIFACT_DIR",
                            "/home/bot/55chat-bot/artifacts/physical-feedback",
                        ),
                        f"{kind}_{ts}_{serial.replace(':', '_')}.png",
                    )
                    Path(png_path).write_bytes(png_bytes)
    except Exception as ex:
        log.warning("[PHYSICAL] capture failed serial=%s: %s", serial, ex)

    bubble_ts = extract_latest_bubble_time(texts, ref=api_deadline)
    now_api = datetime.now(BEIJING)
    lag_sec = None
    if bubble_ts:
        lag_sec = (bubble_ts - api_deadline).total_seconds()
    snippet_ok = bool(expected_snippet) and any(
        expected_snippet[:12] in (t or "") for t in texts
    )
    text_join = " | ".join(texts[-8:])
    ms = (time.perf_counter() - t0) * 1000

    result = {
        "ok": True,
        "kind": kind,
        "serial": serial,
        "api_deadline": api_deadline.isoformat(),
        "bubble_ts": bubble_ts.isoformat() if bubble_ts else None,
        "lag_sec": lag_sec,
        "snippet_ok": snippet_ok,
        "expected_snippet": expected_snippet[:40],
        "bottom_text": text_join[:200],
        "ocr_tail": ocr_text[:120],
        "png_path": png_path,
        "verify_ms": round(ms, 1),
    }

    capture_ok = bool(texts) or bool(png_path)
    p0 = False
    if lag_sec is not None and lag_sec > PHYSICAL_LAG_BUDGET_SEC:
        p0 = True
        result["ok"] = False
        result["p0_reason"] = f"bubble_lag_{lag_sec:.1f}s>{PHYSICAL_LAG_BUDGET_SEC}s"
    if expected_snippet and not snippet_ok and capture_ok:
        if OPEN_SNIPPET_P0:
            p0 = True
            result["ok"] = False
            result["p0_reason"] = result.get("p0_reason", "") + ";snippet_missing"
        else:
            result["degraded"] = "snippet_suppressed"
            log.warning(
                "[PHYSICAL] snippet miss — P0/heal suppressed kind=%s snip=%s",
                kind,
                expected_snippet[:24],
            )
    elif expected_snippet and not snippet_ok and not capture_ok:
        result["degraded"] = "capture_empty_skip_p0"
        log.warning("[PHYSICAL] 跳过 P0：截屏/OCR 无数据 kind=%s", kind)

    if p0:
        _emit_p0(result)
        try:
            from bot_ops.sre_self_heal import trigger_self_heal

            trigger_self_heal(result.get("p0_reason") or "physical_p0", force=False)
        except Exception as ex:
            log.warning("[PHYSICAL] self-heal hook failed: %s", ex)
    else:
        log.info(
            "[PHYSICAL] OK kind=%s lag=%s snippet=%s ms=%.0f png=%s",
            kind, lag_sec, snippet_ok, ms, os.path.basename(png_path or ""),
        )
    return result


def _emit_p0(payload: dict[str, Any]) -> None:
    payload = {**payload, "ts": time.time(), "level": "P0"}
    log.error("[P0 PHYSICAL] %s", json.dumps(payload, ensure_ascii=False)[:500])
    try:
        os.makedirs(os.path.dirname(P0_ALERT_FILE), exist_ok=True)
        with open(P0_ALERT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as ex:
        log.warning("P0 alert write failed: %s", ex)


def rollback_announce_resend_hint(serial: str, kind: str, rid: int) -> None:
    """P0 触发：清除 dedupe 标记，允许公告线程重发。"""
    log.warning("[P0 ROLLBACK] 请求重发 kind=%s rid=%s serial=%s", kind, rid, serial)
