"""VPS / bot configuration loading."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VpsConfig:
    host: str
    user: str
    password: str
    bot_root: str
    listener_adb_port: str = "60478"
    clicker_adb_port: str = "56121"
    key_path: str = ""


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_vps_config(root: Path | None = None) -> VpsConfig:
    root = root or Path(__file__).resolve().parents[1]
    file_env = _parse_env_file(root / "config" / "vps-ssh.env")
    merged = {**file_env, **{k: v for k, v in os.environ.items() if k.startswith("VPS_") or k == "BOT_ROOT"}}

    host = merged.get("VPS_HOST", "").strip()
    user = merged.get("VPS_USER", "root").strip() or "root"
    password = merged.get("VPS_PASSWORD", "").strip()
    key_path = merged.get("VPS_KEY_PATH", "").strip()
    bot_root = merged.get("BOT_ROOT", "/home/bot/55chat-bot").strip() or "/home/bot/55chat-bot"

    if not host:
        raise RuntimeError(
            "缺少 VPS 凭证: 请配置 config/vps-ssh.env (VPS_HOST) 或设置 VPS_HOST 环境变量"
        )
    if not password and not key_path:
        raise RuntimeError(
            "缺少 VPS 凭证: 请配置 VPS_PASSWORD 或 VPS_KEY_PATH"
        )

    listener_port = "60478"
    clicker_port = "56121"
    bot_start = root / "config" / "bot-start.env"
    if bot_start.is_file():
        bot_env = _parse_env_file(bot_start)
        listener_port = bot_env.get("BOT_LISTENER_ADB_PORT", listener_port)
        clicker_port = bot_env.get("BOT_CLICKER_ADB_PORT", clicker_port)

    return VpsConfig(
        host=host,
        user=user,
        password=password,
        bot_root=bot_root,
        listener_adb_port=listener_port,
        clicker_adb_port=clicker_port,
        key_path=key_path,
    )
