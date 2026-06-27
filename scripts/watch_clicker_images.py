#!/usr/bin/env python3
"""左机发图：log + 抓屏 + UI ImageView，成功才停。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops import load_vps_config  # noqa: E402
from bot_ops.clicker_watch import run_image_watch  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402
from bot_tunnel import load_env_file  # noqa: E402

POLL_SEC = int(os.environ.get("CLICKER_WATCH_POLL_SEC", "25"))
MAX_MIN = int(os.environ.get("CLICKER_WATCH_MAX_MIN", "45"))


def _group_name(root: Path) -> str:
    bot_env = load_env_file(root / "config" / "bot-start.env")
    return (bot_env.get("BOT_ASSOCIATED_GROUP") or bot_env.get("ASSOCIATED_GROUP") or "").strip()


def _clicker_serial(config) -> str:
    port = config.clicker_adb_port
    return f"127.0.0.1:{port}"


def main() -> int:
    try:
        config = load_vps_config(ROOT)
    except RuntimeError as ex:
        print(f"[FAIL] VPS: {ex}")
        return 1
    group = _group_name(ROOT)
    if not group:
        print("[FAIL] 缺少 config/bot-start.env 中的 BOT_ASSOCIATED_GROUP", file=sys.stderr)
        return 1
    with VpsSSH(config) as ssh:
        return run_image_watch(
            ssh,
            config_bot_root=config.bot_root,
            local_root=ROOT,
            serial=_clicker_serial(config),
            group_name=group,
            poll_sec=POLL_SEC,
            max_min=MAX_MIN,
        )


if __name__ == "__main__":
    raise SystemExit(main())
