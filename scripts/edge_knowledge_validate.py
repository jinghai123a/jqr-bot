#!/usr/bin/env python3
"""校验 config/55m-knowledge/*.json 可加载且关键字段存在。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "config" / "55m-knowledge"

REQUIRED = [
    "oss-stack.json",
    "apis.json",
    "apks.json",
    "coords.json",
    "announce-templates.json",
    "chat-commands.json",
    "control-plane.json",
    "ui-pages.json",
    "edge-events.json",
    "executor-matrix.json",
    "panel-catalog.json",
]


def main() -> int:
    for name in REQUIRED:
        p = KB / name
        if not p.is_file():
            print(f"MISSING {p}")
            return 1
        data = json.loads(p.read_text(encoding="utf-8"))
        if not data:
            print(f"EMPTY {p}")
            return 1
    oss = json.loads((KB / "oss-stack.json").read_text(encoding="utf-8"))
    assert oss.get("locked") and oss.get("stacks"), "oss-stack invalid"
    matrix = json.loads((KB / "executor-matrix.json").read_text(encoding="utf-8"))
    assert "edge_124" in matrix.get("modes", {}) or "dual_supervisor" in matrix.get("modes", {}), "executor-matrix invalid"
    assert "desktop_ws" in matrix.get("modes", {}), "executor-matrix missing desktop_ws"
    dp = KB / "desktop-protocol.json"
    if dp.is_file():
        json.loads(dp.read_text(encoding="utf-8"))
    catalog = KB / "panel-catalog.json"
    if catalog.is_file():
        cat = json.loads(catalog.read_text(encoding="utf-8"))
        assert isinstance(cat.get("products"), list) and cat["products"], "panel-catalog products empty"
        assert isinstance(cat.get("combo_rules"), list) and cat["combo_rules"], "panel-catalog combo_rules empty"
    print(f"KNOWLEDGE_OK {len(REQUIRED)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
