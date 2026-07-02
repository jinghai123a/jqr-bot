"""全局运行时配置 — ADB 端口 / Bot ID / env 单一真相源。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BEIJING_TZ_NAME = "Asia/Shanghai"
DEFAULT_LISTENER_PORT = "58433"
DEFAULT_CLICKER_PORT = "52840"
DEFAULT_LISTENER_ID = "bot-4"
DEFAULT_CLICKER_IDS = ("bot-3",)


def _root() -> Path:
    return Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))


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


@dataclass(frozen=True)
class BotRuntime:
    root: Path
    listener_adb_port: str
    clicker_adb_port: str
    listener_serial: str
    clicker_serial: str
    listener_id: str
    clicker_ids: tuple[str, ...]
    listener_adb_server: int
    clicker_adb_server: int
    dual_process: bool
    adb_isolated: bool


@lru_cache(maxsize=1)
def load_bot_runtime(root: Path | None = None) -> BotRuntime:
    root = root or _root()
    file_env = _parse_env_file(root / "config" / "bot-start.env")

    force_from_file = {
        "BOT_LISTENER_ADB_PORT",
        "BOT_CLICKER_ADB_PORT",
        "BOT_LISTENER_ID",
        "BOT_CLICKER_IDS",
        "BOT_CLICKER_ID",
        "BOT_DUAL_PROCESS",
        "BOT_ADB_ISOLATED",
        "BOT_LISTENER_ADB_SERVER_PORT",
        "BOT_CLICKER_ADB_SERVER_PORT",
    }

    def _get(key: str, default: str = "") -> str:
        if key in force_from_file and key in file_env:
            return file_env[key].strip().strip('"').strip("'")
        return os.environ.get(key, file_env.get(key, default)).strip()

    lp = _get("BOT_LISTENER_ADB_PORT", DEFAULT_LISTENER_PORT)
    cp = _get("BOT_CLICKER_ADB_PORT", DEFAULT_CLICKER_PORT)
    lid = _get("BOT_LISTENER_ID", DEFAULT_LISTENER_ID)
    raw_clickers = _get("BOT_CLICKER_IDS") or _get("BOT_CLICKER_ID", DEFAULT_CLICKER_IDS[0])
    cids = tuple(x.strip() for x in raw_clickers.split(",") if x.strip()) or DEFAULT_CLICKER_IDS
    return BotRuntime(
        root=root,
        listener_adb_port=lp,
        clicker_adb_port=cp,
        listener_serial=f"localhost:{lp}",
        clicker_serial=f"localhost:{cp}",
        listener_id=lid,
        clicker_ids=cids,
        listener_adb_server=int(_get("BOT_LISTENER_ADB_SERVER_PORT", "5038") or 5038),
        clicker_adb_server=int(_get("BOT_CLICKER_ADB_SERVER_PORT", "5039") or 5039),
        dual_process=_get("BOT_DUAL_PROCESS", "1") in ("1", "true", "yes"),
        adb_isolated=_get("BOT_ADB_ISOLATED", "1") in ("1", "true", "yes"),
    )


def apply_bot_start_env(root: Path | None = None) -> BotRuntime:
    """将 bot-start.env 注入 os.environ（daemon/supervisor 启动时调用）。"""
    root = root or _root()
    file_env = _parse_env_file(root / "config" / "bot-start.env")
    # 端口/角色以文件为准，禁止陈旧 os.environ（如 52840）覆盖 bot-start.env
    force_keys = (
        "BOT_LISTENER_ADB_PORT",
        "BOT_CLICKER_ADB_PORT",
        "BOT_LISTENER_ID",
        "BOT_CLICKER_IDS",
        "BOT_CLICKER_ID",
        "BOT_DUAL_PROCESS",
        "BOT_ADB_ISOLATED",
        "BOT_LISTENER_ADB_SERVER_PORT",
        "BOT_CLICKER_ADB_SERVER_PORT",
        "BOT_CLICKER_SEND_IMAGES",
        "BOT_CLICKER_STAY_IN_CHAT",
        "BOT_LISTENER_AUTO_RECOVER",
        "BOT_LISTENER_WEBVIEW_AUTO_BACK",
        "BOT_LISTENER_STAY_LOOP",
    )
    preserved_role = (os.environ.get("BOT_ROLE") or "").strip()
    for k, v in file_env.items():
        if k == "BOT_ROLE":
            if preserved_role:
                continue
            if not (v or "").strip():
                continue
        if k in force_keys:
            os.environ[k] = v
        else:
            os.environ.setdefault(k, v)
    if preserved_role:
        os.environ["BOT_ROLE"] = preserved_role
    load_bot_runtime.cache_clear()
    rt = load_bot_runtime(root)
    os.environ["BOT_LISTENER_ADB_PORT"] = rt.listener_adb_port
    os.environ["BOT_CLICKER_ADB_PORT"] = rt.clicker_adb_port
    os.environ.setdefault("BOT_LISTENER_ID", rt.listener_id)
    os.environ.setdefault("BOT_CLICKER_IDS", ",".join(rt.clicker_ids))
    return rt


def serial_for_port(port: str) -> str:
    p = (port or "").strip()
    if ":" in p:
        return p
    return f"localhost:{p}"
