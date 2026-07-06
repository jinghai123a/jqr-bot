#!/usr/bin/env python3
"""Verify local venv has all required modules."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODS = [
    "fastapi",
    "uvicorn",
    "httpx",
    "PIL",
    "jwt",
    "paramiko",
    "numpy",
    "cv2",
    "adbutils",
    "uiautomator2",
    "pytest",
    "edge_brain",
    "bot_ops",
    "board_capture",
]

failed: list[tuple[str, str]] = []
for name in MODS:
    try:
        importlib.import_module(name)
        print(f"OK {name}")
    except Exception as exc:
        failed.append((name, str(exc)))
        print(f"FAIL {name}: {exc}")

if failed:
    sys.exit(1)
print("VERIFY_OK")
