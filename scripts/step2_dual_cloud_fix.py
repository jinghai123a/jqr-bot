#!/usr/bin/env python3
"""Step2：双云机 + APS 隧道/断点对齐（本机调 VMOS API → VPS 重连）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    print("=== vmos-pads ===")
    print(json.dumps(pads, ensure_ascii=False, indent=2))

    print("\n=== local VMOS API refresh ===")
    rc = subprocess.call([sys.executable, str(ROOT / "scripts" / "vmos_api_local_refresh.py")])
    if rc != 0:
        print("WARN: local refresh exit", rc)

    print("\n=== post-check ===")
    subprocess.call([sys.executable, str(ROOT / "scripts" / "step1_architecture_audit.py")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
