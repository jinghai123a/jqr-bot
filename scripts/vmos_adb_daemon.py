#!/usr/bin/env python3
"""
VMOS Cloud OpenAPI 动态 ADB 续期守护进程。

官方每 24h 轮换 ADB 密钥；本守护在过期前（默认提前 2h）或断链时调用：
  openOnlineAdb → wait taskStatus=3 → padApi/adb → 写 tunnel-*.env → reconnect

用法:
  python scripts/vmos_adb_daemon.py --once          # 单轮（cron 可调用）
  python scripts/vmos_adb_daemon.py --daemon      # 永久后台循环
  python scripts/vmos_adb_daemon.py --status      # 过期时间与守护状态
  python scripts/vmos_adb_daemon.py --urgent      # 标记下一轮立即 OpenAPI 刷新
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _bootstrap_env() -> None:
    from bot_tunnel.env_io import load_env_file

    for key, val in load_env_file(ROOT / "config" / "bot-start.env").items():
        os.environ.setdefault(key, val)


_bootstrap_env()

from bot_tunnel.daemon import (  # noqa: E402
    DaemonConfig,
    build_daemon_sides,
    load_daemon_state,
    request_urgent_refresh,
    run_daemon_cycle,
    run_forever,
)
from bot_tunnel.env_io import load_env_file  # noqa: E402
from bot_tunnel.expire_schedule import format_expire_status, print_expire_status_table  # noqa: E402
from scripts.vmos_api.transport import proxy_from_env  # noqa: E402
from vmos_api_client import VmosApiClient  # noqa: E402


def _make_client() -> VmosApiClient:
    api_env = load_env_file(ROOT / "config" / "vmos-api.env")
    ak = api_env.get("VMOS_ACCESS_KEY") or api_env.get("VMOS_AK") or ""
    sk = api_env.get("VMOS_SECRET_KEY") or api_env.get("VMOS_SK") or ""
    if not ak or not sk:
        raise RuntimeError("missing VMOS_ACCESS_KEY/VMOS_SECRET_KEY in config/vmos-api.env")
    proxy = proxy_from_env(api_env)
    return VmosApiClient(ak, sk, timeout=90, proxy=proxy or None)


def _cmd_status() -> int:
    sides = build_daemon_sides(ROOT)
    rows = []
    for side, cfg in sides.items():
        rows.append(format_expire_status(side, cfg["tunnel_file"], pad_code=str(cfg.get("pad_code") or "")))
    print_expire_status_table(rows)
    state = load_daemon_state(ROOT)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="VMOS OpenAPI dynamic ADB renewal daemon")
    parser.add_argument("--daemon", action="store_true", help="run forever (background service)")
    parser.add_argument("--once", action="store_true", help="single renewal cycle")
    parser.add_argument("--status", action="store_true", help="print expiry + daemon state")
    parser.add_argument("--urgent", action="store_true", help="flag next cycle for immediate API refresh")
    parser.add_argument("--poll-sec", type=int, default=int(os.environ.get("BOT_VMOS_DAEMON_POLL_SEC", "300")))
    parser.add_argument(
        "--api-cooldown-sec",
        type=int,
        default=int(os.environ.get("BOT_VMOS_DAEMON_API_COOLDOWN_SEC", "1800")),
    )
    args = parser.parse_args()

    if args.urgent:
        request_urgent_refresh(ROOT)
        print("urgent flag set")
        return 0

    if args.status:
        return _cmd_status()

    cfg = DaemonConfig(poll_sec=args.poll_sec, api_cooldown_sec=args.api_cooldown_sec)

    if args.daemon:
        run_forever(ROOT, _make_client, cfg=cfg)
        return 0

    # default: --once
    return run_daemon_cycle(ROOT, _make_client(), cfg=cfg)


if __name__ == "__main__":
    raise SystemExit(main())
