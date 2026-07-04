#!/usr/bin/env python3
"""将 config/pinned-coords.json 同步到 edge_android/*/edge_config.json。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_jwt(path: Path) -> str:
    import os

    if os.environ.get("EDGE_BRAIN_JWT", "").strip():
        return os.environ["EDGE_BRAIN_JWT"].strip()
    if path.is_file():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old.get("jwt"):
            return str(old["jwt"])
    if os.environ.get("EDGE_BRAIN_JWT_SECRET", "").strip():
        from bot_ops.auth import encode_token

        return encode_token(sub="edge-service")
    raise SystemExit("EDGE_BRAIN_JWT or EDGE_BRAIN_JWT_SECRET required")


def main() -> int:
    pinned = json.loads((ROOT / "config" / "pinned-coords.json").read_text(encoding="utf-8"))
    clicker = pinned.get("clicker") or {}
    listener = pinned.get("listener") or {}

    attach = clicker.get("attach_image_bottom") or clicker.get("attach_image") or [90, 1110]

    left_path = ROOT / "edge_android" / "settle-left" / "edge_config.json"
    right_path = ROOT / "edge_android" / "listener-right" / "edge_config.json"
    jwt = _load_jwt(left_path)

    left_cfg = {
        "brain_url": "http://127.0.0.1:8790",
        "jwt": jwt,
        "dcim_dir": "/sdcard/DCIM/Camera/",
        "coords": {
            "chat_plus": clicker.get("chat_plus", [45, 1235]),
            "attach_image": attach,
            "attach_image_bottom": clicker.get("attach_image_bottom", attach),
            "gallery_check_top3": clicker.get(
                "gallery_check_top3", [[654, 374], [429, 374], [205, 374]]
            ),
            "gallery_batch_send": clicker.get("gallery_batch_send", [668, 1210]),
        },
        "_synced_from": "config/pinned-coords.json",
    }

    right_cfg = {
        "brain_url": "http://127.0.0.1:8790",
        "jwt": jwt,
        "coords": {
            "send": listener.get("send", [674, 1234]),
            "keyboard_send": listener.get("keyboard_send", [675, 1190]),
            "input": listener.get("input", [360, 1234]),
        },
        "_synced_from": "config/pinned-coords.json",
    }

    left_path = ROOT / "edge_android" / "settle-left" / "edge_config.json"
    right_path = ROOT / "edge_android" / "listener-right" / "edge_config.json"
    left_path.write_text(json.dumps(left_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    right_path.write_text(json.dumps(right_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SYNC_OK left={left_path.relative_to(ROOT)} right={right_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
