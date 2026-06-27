#!/usr/bin/env python3
"""VPS 双机轻量巡检：ADB/在群/daemon；异常自动拉隧道或重启。勿与发图探针并发。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.watch import run_watch_cycle  # noqa: E402


def main() -> int:
    return run_watch_cycle()


if __name__ == "__main__":
    sys.exit(main())
