"""双机 ADB 物理隔离：52363 / 59162 各走独立 adb server 端口。"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Sequence

log = logging.getLogger(__name__)

DEFAULT_SERVER = 5037


def _runtime():
    from bot_ops.runtime import load_bot_runtime

    return load_bot_runtime()


def adb_server_port(serial: str) -> int:
    rt = _runtime()
    if not rt.adb_isolated:
        return DEFAULT_SERVER
    dp = (serial or "").rsplit(":", 1)[-1]
    # serial 端口优先于本进程 BOT_ROLE（LISTENER 进程也要能调左机 5039）
    if dp == rt.clicker_adb_port:
        return rt.clicker_adb_server
    if dp == rt.listener_adb_port:
        return rt.listener_adb_server
    role = os.environ.get("BOT_ROLE", "").upper()
    if role == "CLICKER":
        return rt.clicker_adb_server
    if role == "LISTENER":
        return rt.listener_adb_server
    log.warning("[ADB-ISOLATE] serial=%s role=%s → fallback 5037", serial, role or "?")
    return DEFAULT_SERVER


def adb_cmd(serial: str, *args: str) -> list[str]:
    return ["adb", "-P", str(adb_server_port(serial)), "-s", serial, *args]


def adb_exec_cmd(serial: str, *args: str) -> list[str]:
    return ["adb", "-P", str(adb_server_port(serial)), "-s", serial, "exec-out", *args]


def _run_quiet(cmd: Sequence[str], timeout: int = 15) -> None:
    try:
        subprocess.run(list(cmd), capture_output=True, timeout=timeout, check=False)
    except Exception as ex:
        log.debug("adb isolate: %s", ex)


def ensure_adb_servers() -> None:
    rt = _runtime()
    if not rt.adb_isolated:
        _run_quiet(["adb", "start-server"])
        return
    for port in (rt.listener_adb_server, rt.clicker_adb_server):
        _run_quiet(["adb", "-P", str(port), "start-server"])
    _run_quiet(["adb", "-P", str(rt.listener_adb_server), "connect", rt.listener_serial])
    _run_quiet(["adb", "-P", str(rt.clicker_adb_server), "connect", rt.clicker_serial])
    log.info(
        "[ADB-ISOLATE] %s→P%d %s→P%d",
        rt.listener_serial,
        rt.listener_adb_server,
        rt.clicker_serial,
        rt.clicker_adb_server,
    )
