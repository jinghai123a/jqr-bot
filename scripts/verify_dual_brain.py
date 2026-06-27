#!/usr/bin/env python3
"""双脑硬性验收：部署/改代码后必须跑，无需 W49 提醒。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops import load_vps_config, run_verify_dual_brain  # noqa: E402


def main() -> int:
    try:
        config = load_vps_config(ROOT)
    except RuntimeError as ex:
        print(f"[FAIL] VPS SSH: {ex}")
        return 1
    return run_verify_dual_brain(config)


if __name__ == "__main__":
    sys.exit(main())
