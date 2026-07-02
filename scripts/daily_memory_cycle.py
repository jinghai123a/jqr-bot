#!/usr/bin/env python3
"""铁律 #7：每日北京时间 19:35（维护窗后）— 磁盘清理 → 内存落盘（云机 OpenAPI + VPS，不占隧道）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from bot_ops.daily_memory_cycle import run_daily_memory_cycle
    from bot_ops.runtime import apply_bot_start_env

    apply_bot_start_env(ROOT)
    report = run_daily_memory_cycle(ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
