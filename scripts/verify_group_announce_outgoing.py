#!/usr/bin/env python3
"""验证双机群聊是否存在机器人发出的公告气泡（OUT），非仅 IN/历史文案。"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if "fcntl" not in sys.modules:
    import types

    sys.modules["fcntl"] = types.ModuleType("fcntl")

import bot_55chat_daemon as d  # noqa: E402
from bot_ops.announce_audit import ANNOUNCE_MARKERS, extract_announce_bubbles, summarize_bubbles  # noqa: E402


def _edge_brain_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _scan_side(serial: str, bot: dict, *, scrolls: int) -> dict[str, object]:
    d.scroll_chat_toward_bottom(serial, max(1, scrolls))
    root = d.ui_hierarchy(serial, force=True)
    ctx = d.describe_screen_context(root, bot, serial)
    sw = d.screen_width(root) if root is not None else 720
    nodes: list[tuple[str, int, int, int, int]] = []
    if root is not None:
        for node in root.iter("node"):
            t = (node.attrib.get("text") or "").strip()
            b = d.parse_bounds(node.attrib.get("bounds", ""))
            if not b:
                continue
            nodes.append((t, b[0], b[1], b[2], b[3]))
    bubbles = extract_announce_bubbles(nodes, sw)
    summary = summarize_bubbles(bubbles)
    return {
        "serial": serial,
        "bot_id": bot.get("id"),
        "page": ctx.page,
        "in_target_group": d.in_target_group_chat(root, bot, serial),
        "markers": list(ANNOUNCE_MARKERS),
        **summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", default="localhost:50185")
    ap.add_argument("--right", default="localhost:61573")
    ap.add_argument("--group", default="苍井空测试")
    ap.add_argument("--scrolls", type=int, default=3)
    ap.add_argument("--edge-url", default="http://127.0.0.1:8790")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = {
        "edge_brain_up": _edge_brain_ok(args.edge_url),
        "left": _scan_side(args.left, {"id": "bot-3", "associatedGroup": args.group}, scrolls=args.scrolls),
        "right": _scan_side(args.right, {"id": "bot-4", "associatedGroup": args.group}, scrolls=args.scrolls),
    }
    report["any_bot_sent_announce"] = bool(
        report["left"]["bot_sent_evidence"] or report["right"]["bot_sent_evidence"]
    )
    report["verdict"] = (
        "PASS" if report["any_bot_sent_announce"] else "FAIL_NO_OUTGOING_ANNOUNCE"
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"edge_brain={report['edge_brain_up']} verdict={report['verdict']}")
        for side in ("left", "right"):
            row = report[side]
            print(
                f"[{side}] serial={row['serial']} page={row['page']} "
                f"in_target={row['in_target_group']} OUT={row['out_count']} IN={row['in_count']}"
            )
            for b in row.get("bubbles", []):
                print(f"  {b['side']} cx={b['cx']} {b['snippet'][:120]}")

    return 0 if report["any_bot_sent_announce"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
