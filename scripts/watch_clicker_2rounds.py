#!/usr/bin/env python3
"""左机发图：群里可见 ImageView + 连续 N 期批量发图成功才停。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops import load_vps_config  # noqa: E402
from bot_ops.clicker_watch import run_consecutive_rounds_watch  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402
from bot_tunnel import load_env_file  # noqa: E402


def _group_name(root: Path) -> str:
    bot_env = load_env_file(root / "config" / "bot-start.env")
    return (bot_env.get("BOT_ASSOCIATED_GROUP") or bot_env.get("ASSOCIATED_GROUP") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--need", type=int, default=2, help="连续成功期数")
    parser.add_argument("--max-min", type=int, default=int(os.environ.get("CLICKER_WATCH_MAX_MIN", "90")))
    parser.add_argument("--poll", type=int, default=25)
    args = parser.parse_args()

    try:
        config = load_vps_config(ROOT)
    except RuntimeError as ex:
        print(f"[FAIL] VPS: {ex}")
        return 1
    group = _group_name(ROOT)
    if not group:
        print("[FAIL] 缺少 BOT_ASSOCIATED_GROUP", file=sys.stderr)
        return 1
    serial = f"127.0.0.1:{config.clicker_adb_port}"
    with VpsSSH(config) as ssh:
        return run_consecutive_rounds_watch(
            ssh,
            config_bot_root=config.bot_root,
            local_root=ROOT,
            serial=serial,
            group_name=group,
            need=args.need,
            poll_sec=args.poll,
            max_min=args.max_min,
        )


if __name__ == "__main__":
    raise SystemExit(main())
