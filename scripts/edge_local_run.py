#!/usr/bin/env python3
"""本地：安装 edge 依赖 → pytest → 启动 brain 冒烟。"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements-edge.txt")],
    )
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_edge_brain.py", "tests/test_clicker_settle.py", "tests/test_capture_ipc.py", "-q"],
        cwd=str(ROOT),
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "edge_brain"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8790/health", timeout=1) as r:
                    if r.status == 200:
                        print("edge_brain local OK :8790")
                        return 0
            except Exception:
                time.sleep(0.3)
        print("edge_brain failed to start", file=sys.stderr)
        return 1
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
