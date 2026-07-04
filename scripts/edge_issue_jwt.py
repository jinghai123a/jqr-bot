#!/usr/bin/env python3
"""签发 Edge Brain 服务 JWT，写入 edge_config / 打印 env。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.auth import encode_token

EDGE_CONFIGS = (
    ROOT / "edge_android/settle-left/edge_config.json",
    ROOT / "edge_android/listener-right/edge_config.json",
)


def _write_edge_configs(token: str) -> None:
    for path in EDGE_CONFIGS:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("token", None)
        data["jwt"] = token
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"updated {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-edge-config", action="store_true")
    ap.add_argument("--ttl-days", type=int, default=365)
    args = ap.parse_args()
    if not os.environ.get("EDGE_BRAIN_JWT_SECRET", "").strip():
        print("ERROR: EDGE_BRAIN_JWT_SECRET required", file=sys.stderr)
        return 1
    token = encode_token(sub="edge-service", ttl_sec=max(3600, args.ttl_days * 86400))
    print(token)
    print(f"EDGE_BRAIN_JWT={token}")
    if args.write_edge_config:
        _write_edge_configs(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
