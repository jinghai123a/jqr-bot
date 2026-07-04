#!/usr/bin/env python3
"""宿主机一键测试（ISO/VM 未就绪时仍跑单元+冒烟）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def run(cmd: list[str], label: str) -> int:
    print(f"\n=== {label} ===")
    r = subprocess.run(cmd, cwd=str(ROOT))
    return r.returncode


def main() -> int:
    steps: list[tuple[list[str], str]] = [
        ([PY, "scripts/edge_knowledge_validate.py"], "knowledge"),
        ([PY, "-m", "pytest", "tests/test_edge_brain.py", "tests/test_clicker_settle.py",
          "tests/test_capture_ipc.py", "tests/test_bot_tunnel.py", "tests/test_bot_ops.py", "-q"], "pytest"),
        ([PY, "scripts/edge_local_run.py"], "edge_brain smoke"),
    ]
    rc = 0
    for cmd, label in steps:
        if run(cmd, label) != 0:
            rc = 1
    print("\nHOST_TEST_SUITE", "OK" if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
