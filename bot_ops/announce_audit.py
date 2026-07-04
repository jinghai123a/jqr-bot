"""群公告 UI 审计：区分 IN/OUT 气泡（W49 闭环以 OUT 为准）。"""
from __future__ import annotations

from typing import Iterable

ANNOUNCE_MARKERS: tuple[str, ...] = (
    "新的一局",
    "已封盘",
    "距离封盘",
    "距封盘",
    "停止下注",
    "期】",
    "六合",
    "走势图",
)

DEFAULT_INCOMING_X_RATIO = 0.55


def classify_bubble_side(cx: int, screen_width: int, *, ratio: float = DEFAULT_INCOMING_X_RATIO) -> str:
    """cx ≤ 屏宽*ratio 为左侧入站 IN，否则为出站 OUT。"""
    return "IN" if cx <= int(screen_width * ratio) else "OUT"


def extract_announce_bubbles(
    nodes: Iterable[tuple[str, int, int, int, int]],
    screen_width: int,
    *,
    markers: tuple[str, ...] = ANNOUNCE_MARKERS,
    ratio: float = DEFAULT_INCOMING_X_RATIO,
) -> list[dict[str, object]]:
    """nodes: (text, x1, y1, x2, y2)"""
    out: list[dict[str, object]] = []
    for text, x1, _y1, x2, _y2 in nodes:
        t = (text or "").strip()
        if len(t) < 6 or not any(m in t for m in markers):
            continue
        cx = (x1 + x2) // 2
        out.append(
            {
                "side": classify_bubble_side(cx, screen_width, ratio=ratio),
                "cx": cx,
                "snippet": t.replace("\n", "|")[:160],
            }
        )
    return out


def summarize_bubbles(bubbles: list[dict[str, object]]) -> dict[str, object]:
    out_n = sum(1 for b in bubbles if b.get("side") == "OUT")
    in_n = sum(1 for b in bubbles if b.get("side") == "IN")
    return {
        "out_count": out_n,
        "in_count": in_n,
        "bot_sent_evidence": out_n > 0,
        "bubbles": bubbles,
    }
