#!/usr/bin/env python3
"""云机实况验收：ADB 读屏 + 截图 + 发送环回，不只盯日志。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops import load_vps_config, run_live_verify  # noqa: E402


def main() -> int:
    try:
        config = load_vps_config(ROOT)
    except RuntimeError as ex:
        print(f"[FAIL] VPS SSH: {ex}")
        return 1
    return run_live_verify(config, art_dir=ROOT / "artifacts" / "live-verify")


if __name__ == "__main__":
    sys.exit(main())
