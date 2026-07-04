#!/usr/bin/env python3
"""APS/VPS 生产部署（本地 E2E 通过后执行，与 edge_auto_all VPS 段一致）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    path = ROOT / "scripts" / "edge_auto_all.py"
    spec = importlib.util.spec_from_file_location("edge_auto_all", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("edge_auto_all load failed")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    mod.vps_auto()
    print("APS_DEPLOY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
