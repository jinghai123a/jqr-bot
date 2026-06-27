"""将 vendor/ 下开源 RPA 源码加入 sys.path（可选，不污染全局除非显式调用）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_VENDOR = _ROOT / "vendor"
_INITED = False


def ensure_vendor_path() -> None:
    global _INITED
    if _INITED:
        return
    paths = [
        _VENDOR / "airtest",
        _VENDOR / "adbutils",
    ]
    for p in paths:
        ps = str(p)
        if p.is_dir() and ps not in sys.path:
            sys.path.insert(0, ps)
    _INITED = True


def vendor_enabled() -> bool:
    return os.environ.get("BOT_RPA_VENDOR", "0").lower() in ("1", "true", "yes")


def maybe_init_vendor() -> None:
    if vendor_enabled():
        ensure_vendor_path()
