#!/usr/bin/env python3
"""从 config/tunnel-creds.local.env 加载 W49 手动凭证并应用（归一化 58433/52840）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_tunnel.env_io import load_env_file


def main() -> int:
    creds = ROOT / "config" / "tunnel-creds.local.env"
    if not creds.exists():
        print("缺少 config/tunnel-creds.local.env", file=sys.stderr)
        return 1
    for k, v in load_env_file(creds).items():
        os.environ[k] = v
    os.environ.setdefault("TUNNEL_SIDES", "both")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "apply_dual_tunnel_manual",
        ROOT / "scripts" / "apply_dual_tunnel_manual.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("apply_dual_tunnel_manual load failed")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
