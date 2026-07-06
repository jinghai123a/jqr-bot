"""VMOS ADB 动态续期守护 — 单轮决策与执行（OpenAPI padApi/adb）。"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .adb_probe import adb_probe_port
from .env_io import load_env_file
from .expire_schedule import (
    format_expire_status,
    minutes_until_expire,
    refresh_buffer_minutes,
    should_refresh_tunnel,
)
from .lock import acquire_refresh_lock
from .pad_resolve import resolve_pad_code
from .refresh import reconnect_sides, refresh_side_credentials

BJ = ZoneInfo("Asia/Shanghai")
STATE_FILE = "data/vmos_adb_daemon.json"
URGENT_FLAG = "data/vmos_adb_daemon.urgent"
DEFAULT_POLL_SEC = 300
DEFAULT_API_COOLDOWN_SEC = 1800
DEFAULT_MAX_API_ATTEMPTS = 3


def _ts() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_ts()}] {msg}", flush=True)


@dataclass
class DaemonConfig:
    poll_sec: int = DEFAULT_POLL_SEC
    api_cooldown_sec: int = DEFAULT_API_COOLDOWN_SEC
    max_api_attempts: int = DEFAULT_MAX_API_ATTEMPTS
    buffer_minutes: int = field(default_factory=refresh_buffer_minutes)


@dataclass
class SidePlan:
    side: str
    reason: str
    api_refresh: bool
    reconnect_only: bool = False


def load_daemon_state(root: Path) -> dict[str, Any]:
    path = root / STATE_FILE
    if not path.is_file():
        return {"sides": {}, "last_cycle": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"sides": {}, "last_cycle": None}


def save_daemon_state(root: Path, state: dict[str, Any]) -> None:
    path = root / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    state["last_cycle"] = _ts()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def consume_urgent_flag(root: Path) -> bool:
    flag = root / URGENT_FLAG
    if not flag.is_file():
        return False
    try:
        flag.unlink()
    except OSError:
        pass
    return True


def request_urgent_refresh(root: Path) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / URGENT_FLAG).write_text(_ts(), encoding="utf-8")


def _api_cooldown_elapsed(state: dict[str, Any], side: str, cooldown_sec: int) -> bool:
    sides = state.get("sides") or {}
    rec = sides.get(side) or {}
    raw = rec.get("last_api_at")
    if not raw:
        return True
    try:
        last = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)
    except ValueError:
        return True
    return (datetime.now(BJ) - last).total_seconds() >= cooldown_sec


def _record_api_refresh(state: dict[str, Any], side: str, *, ok: bool, detail: str) -> None:
    sides = state.setdefault("sides", {})
    sides[side] = {
        "last_api_at": _ts(),
        "last_ok": ok,
        "detail": detail[:500],
    }


def build_daemon_sides(root: Path) -> dict[str, dict[str, Any]]:
    pads_cfg = json.loads((root / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    bot_env = load_env_file(root / "config" / "bot-start.env")
    return {
        "right": {
            **(pads_cfg.get("right") or {}),
            "local_port": bot_env.get("BOT_LISTENER_ADB_PORT", "58433"),
            "tunnel_file": root / "config" / "tunnel-right.env",
            "tunnel_bind": str((pads_cfg.get("right") or {}).get("match_egress_ip") or ""),
        },
        "left": {
            **(pads_cfg.get("left") or {}),
            "local_port": bot_env.get("BOT_CLICKER_ADB_PORT", "55612"),
            "tunnel_file": root / "config" / "tunnel-left.env",
            "tunnel_bind": str((pads_cfg.get("left") or {}).get("match_egress_ip") or ""),
        },
    }


def plan_cycle(
    root: Path,
    sides: dict[str, dict[str, Any]],
    state: dict[str, Any],
    cfg: DaemonConfig,
    *,
    urgent: bool = False,
) -> list[SidePlan]:
    plans: list[SidePlan] = []
    for side, scfg in sides.items():
        port = str(scfg["local_port"])
        tunnel_file: Path = scfg["tunnel_file"]
        env = load_env_file(tunnel_file)
        adb_ok = adb_probe_port(port)
        left_min = minutes_until_expire(env)
        expiring = should_refresh_tunnel(env, buffer_minutes=cfg.buffer_minutes)
        cooldown_ok = _api_cooldown_elapsed(state, side, cfg.api_cooldown_sec)

        if adb_ok and not expiring and not urgent:
            continue

        if not adb_ok and not cooldown_ok and not expiring:
            plans.append(SidePlan(side, "adb_offline_cooldown_reconnect", api_refresh=False, reconnect_only=True))
            continue

        if expiring or not adb_ok or urgent:
            if cooldown_ok or expiring or urgent or left_min is not None and left_min <= 30:
                reason = "expiring" if expiring else ("offline" if not adb_ok else "urgent")
                plans.append(SidePlan(side, reason, api_refresh=True))
            else:
                plans.append(SidePlan(side, "cooldown_wait", api_refresh=False, reconnect_only=not adb_ok))
            continue

    return plans


def run_daemon_cycle(
    root: Path,
    client: Any,
    *,
    cfg: DaemonConfig | None = None,
    pads: list[dict] | None = None,
    models: dict[str, dict] | None = None,
    urgent: bool = False,
) -> int:
    """One daemon iteration: plan → OpenAPI refresh (gentle) → reconnect."""
    cfg = cfg or DaemonConfig()
    sides = build_daemon_sides(root)
    state = load_daemon_state(root)
    urgent = urgent or consume_urgent_flag(root)
    plans = plan_cycle(root, sides, state, cfg, urgent=urgent)

    for side, scfg in sides.items():
        st = format_expire_status(side, scfg["tunnel_file"], pad_code=str(scfg.get("pad_code") or ""))
        _log(
            f"status {side} port={st['local_port']} left_min={st['minutes_left']} "
            f"should_refresh={st['should_refresh']} adb_ok={adb_probe_port(str(scfg['local_port']))}"
        )

    if not plans:
        _log("cycle idle — credentials fresh and ADB online")
        save_daemon_state(root, state)
        return 0

    api_sides: dict[str, dict[str, Any]] = {}
    reconnect_only: list[str] = []
    for p in plans:
        _log(f"plan {p.side} reason={p.reason} api={p.api_refresh} reconnect_only={p.reconnect_only}")
        if p.api_refresh:
            api_sides[p.side] = sides[p.side]
        elif p.reconnect_only:
            reconnect_only.append(p.side)

    if reconnect_only and not api_sides:
        reconnect_sides({s: sides[s] for s in reconnect_only}, root)
        save_daemon_state(root, state)
        return 0

    lock_fp = acquire_refresh_lock(root)
    if lock_fp is None:
        _log("skip — another refresh holds lock")
        return 0

    pads = pads or []
    models = models or {}
    failures: list[str] = []
    try:
        for side, scfg in api_sides.items():
            code = resolve_pad_code(side, scfg, pads, models)
            _log(f"OpenAPI dynamic refresh {side} pad={code} port={scfg['local_port']}")
            ok, failure = refresh_side_credentials(
                side,
                scfg,
                client,
                pads,
                models,
                max_attempts=cfg.max_api_attempts,
            )
            _record_api_refresh(state, side, ok=ok and not failure, detail=failure or "ok")
            if failure:
                failures.append(failure)

        refresh_targets = {**api_sides, **{s: sides[s] for s in reconnect_only}}
        reconnect_sides(refresh_targets, root)

        for side, scfg in refresh_targets.items():
            port = str(scfg["local_port"])
            if adb_probe_port(port):
                _log(f"verify OK {side} :{port}")
            else:
                _log(f"verify FAIL {side} :{port}")
                failures.append(side)
    finally:
        os.close(lock_fp)

    save_daemon_state(root, state)
    return 1 if failures else 0


def run_forever(
    root: Path,
    client_factory: Any,
    *,
    cfg: DaemonConfig | None = None,
) -> None:
    cfg = cfg or DaemonConfig()
    poll = max(60, cfg.poll_sec)
    _log(f"daemon start poll={poll}s cooldown={cfg.api_cooldown_sec}s max_api={cfg.max_api_attempts}")
    pads: list[dict] = []
    models: dict[str, dict] = {}
    while True:
        try:
            client = client_factory()
            run_daemon_cycle(root, client, cfg=cfg, pads=pads, models=models)
        except Exception as exc:
            _log(f"cycle error: {exc}")
        time.sleep(poll)
