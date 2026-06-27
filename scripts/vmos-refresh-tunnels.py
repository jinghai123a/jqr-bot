#!/usr/bin/env python3
"""
从 VMOS Cloud API 拉取最新 SSH/ADB 凭证，更新 config/tunnel-*.env 并重连隧道。

用法:
  cd /home/bot/55chat-bot
  python3 scripts/vmos-refresh-tunnels.py              # 仅更新 env
  python3 scripts/vmos-refresh-tunnels.py --reconnect    # 更新 + 重连 ADB
  python3 scripts/vmos-refresh-tunnels.py --list         # 列出账号下云机
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_tunnel import (  # noqa: E402
    acquire_refresh_lock,
    load_env_file,
    reconnect_sides,
    refresh_side_credentials,
    resolve_pad_code,
)
from scripts.vmos_api_client import VmosApiClient  # noqa: E402


def main() -> int:
    lock_fp = acquire_refresh_lock(ROOT)
    if lock_fp is None:
        print("[skip] another vmos-refresh-tunnels.py is running")
        return 0

    parser = argparse.ArgumentParser()
    parser.add_argument("--reconnect", action="store_true", help="更新 env 后执行 reconnect-dual-adb.sh")
    parser.add_argument("--list", action="store_true", help="仅列出云机")
    parser.add_argument("--side", choices=("all", "right", "left"), default="all", help="只刷新指定侧")
    args = parser.parse_args()

    api_env = load_env_file(ROOT / "config" / "vmos-api.env")
    ak = api_env.get("VMOS_ACCESS_KEY") or api_env.get("VMOS_AK")
    sk = api_env.get("VMOS_SECRET_KEY") or api_env.get("VMOS_SK")
    if not ak or not sk:
        print("缺少 config/vmos-api.env (VMOS_ACCESS_KEY / VMOS_SECRET_KEY)", file=sys.stderr)
        os.close(lock_fp)
        return 1

    client = VmosApiClient(ak, sk)

    pads_cfg_path = ROOT / "config" / "vmos-pads.json"
    pads_cfg = json.loads(pads_cfg_path.read_text(encoding="utf-8")) if pads_cfg_path.exists() else {}

    if args.list:
        pads = client.list_pads(page=1, rows=50)
        pad_codes = [str(p.get("padCode") or "") for p in pads if p.get("padCode")]
        models = {str(m.get("padCode")): m for m in client.model_info(pad_codes)}
        print(json.dumps({"pads": pads, "models": models}, ensure_ascii=False, indent=2))
        os.close(lock_fp)
        return 0

    bot_env = load_env_file(ROOT / "config" / "bot-start.env")
    all_sides = {
        "right": {
            **(pads_cfg.get("right") or {}),
            "local_port": bot_env.get("BOT_LISTENER_ADB_PORT", "49868"),
            "tunnel_file": ROOT / "config" / "tunnel-right.env",
        },
        "left": {
            **(pads_cfg.get("left") or {}),
            "local_port": bot_env.get("BOT_CLICKER_ADB_PORT", "63221"),
            "tunnel_file": ROOT / "config" / "tunnel-left.env",
        },
    }
    sides = all_sides if args.side == "all" else {args.side: all_sides[args.side]}

    need_discover = any(not (cfg.get("pad_code") or "").strip() for cfg in sides.values())
    pads: list[dict] = []
    models: dict[str, dict] = {}
    if need_discover:
        pads = client.list_pads(page=1, rows=50)
        pad_codes = [str(p.get("padCode") or "") for p in pads if p.get("padCode")]
        models = {str(m.get("padCode")): m for m in client.model_info(pad_codes)}

    for side, cfg in sides.items():
        code = resolve_pad_code(side, cfg, pads, models)
        print(f"[{side}] padCode={code} -> port {cfg['local_port']}")

    side_failures: list[str] = []
    for side, cfg in sides.items():
        ok, failure = refresh_side_credentials(side, cfg, client, pads, models)
        if failure:
            side_failures.append(failure)

    if args.reconnect:
        reconnect_sides(sides, ROOT)

    if side_failures and len(side_failures) == len(sides):
        os.close(lock_fp)
        return 1
    if side_failures:
        print(f"[warn] partial refresh failures: {side_failures}")
    os.close(lock_fp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
