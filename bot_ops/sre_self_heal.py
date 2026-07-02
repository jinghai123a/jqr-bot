"""L4 战斗级自愈：3 秒内强杀 → 清队列 → 拉回群 → 重启栈。"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BOT_ROOT = Path(os.environ.get("BOT_ROOT", "/home/bot/55chat-bot"))
SRE_LOG = BOT_ROOT / "logs" / "sre-24h.jsonl"
HEARTBEAT = BOT_ROOT / "data" / "sre-cmd-heartbeat.json"
# 战斗模式：关键故障冷却（秒）— 过小会自愈风暴打满 VPS
HEAL_COOLDOWN_SEC = max(15.0, float(os.environ.get("BOT_SRE_HEAL_COOLDOWN_SEC", "60") or 60))
_last_heal_ts = 0.0


def _append_sre(event: dict[str, Any]) -> None:
    try:
        SRE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SRE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as ex:
        log.warning("[SRE] log write failed: %s", ex)


def touch_cmd_heartbeat(tag: str, **extra: Any) -> None:
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ts": time.time(), "tag": tag, **extra}
        HEARTBEAT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear_outbound_queues() -> None:
    try:
        import bot_55chat_daemon as d

        reg = getattr(d, "_OUTBOUND_BY_SERIAL", None)
        if not reg:
            log.warning("[SRE] _OUTBOUND_BY_SERIAL missing")
            return
        for serial, pool in list(reg.items()):
            n = 0
            while True:
                job = pool.get(timeout=0)
                if not job:
                    break
                n += 1
            if n:
                log.info("[SRE] cleared outbound serial=%s n=%d", serial, n)
    except Exception as ex:
        log.warning("[SRE] outbound clear: %s", ex)


def kill_zombie_processes() -> None:
    try:
        from bot_ops.port_cleanup import kill_listeners_on_ports

        kill_listeners_on_ports((8770,))
    except Exception as ex:
        log.warning("[SRE] port cleanup: %s", ex)
    for pat in ("bot_55chat_daemon", "mock_gateway.py", "bot_dual_supervisor.py"):
        try:
            subprocess.run(["pkill", "-9", "-f", pat], timeout=5, check=False)
        except Exception:
            pass
    lock = BOT_ROOT / "data" / "bot.lock"
    for extra in ("listener", "clicker"):
        p = BOT_ROOT / "data" / f"bot.lock.{extra}"
        if p.is_file():
            try:
                p.unlink()
            except Exception:
                pass
    if lock.is_file():
        try:
            lock.unlink()
        except Exception:
            pass


def recover_listener_group() -> bool:
    """ADB 兜底：右机 message_list / 离群 → 强制回目标群。"""
    try:
        import bot_55chat_daemon as d
        from bot_ops.runtime import load_bot_runtime

        rt = load_bot_runtime()
        bots = d.api("GET", "/api/bots") or []
        bot = next((b for b in bots if str(b.get("id")) == rt.listener_id), None)
        if not bot:
            return False
        serial = rt.listener_serial
        if not d.is_55m_foreground(serial):
            d.launch_messenger_app(serial)
        ok = d.try_recover_listener_to_group(serial, bot, reason="combat-heal", force=True)
        if not ok:
            ok = d.recover_listener_to_group_minimal(serial, bot)
        return bool(ok)
    except Exception as ex:
        log.warning("[SRE] listener recover: %s", ex)
        return False


def reset_adb_tunnels() -> None:
    for script in ("watch-adb-tunnels.sh", "vmos-dual-watchdog.sh"):
        p = BOT_ROOT / "scripts" / script
        if p.is_file():
            try:
                subprocess.run(["bash", str(p)], cwd=str(BOT_ROOT), timeout=90, check=False)
            except Exception as ex:
                log.warning("[SRE] tunnel script %s: %s", script, ex)


def restart_stack(reason: str) -> bool:
    script = BOT_ROOT / "scripts" / "restart-55chat-bot.sh"
    if not script.is_file():
        return False
    try:
        r = subprocess.run(
            ["bash", str(script)],
            cwd=str(BOT_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        ok = r.returncode == 0
        _append_sre(
            {
                "ts": time.time(),
                "action": "restart_stack",
                "reason": reason,
                "ok": ok,
                "stdout": (r.stdout or "")[-400:],
                "stderr": (r.stderr or "")[-400:],
            }
        )
        return ok
    except Exception as ex:
        log.exception("[SRE] restart failed: %s", ex)
        return False


def trigger_self_heal(reason: str, *, force: bool = False) -> bool:
    global _last_heal_ts
    now = time.time()
    snippet_p0 = os.environ.get("BOT_PHYSICAL_OPEN_SNIPPET_P0", "1").lower() in (
        "1",
        "true",
        "yes",
    )
    if "snippet_missing" in (reason or "") and not snippet_p0:
        log.warning("[SRE] heal skipped — snippet P0 suppressed (%s)", reason)
        return False
    if not force and now - _last_heal_ts < HEAL_COOLDOWN_SEC:
        return False
    _last_heal_ts = now
    log.error("[SRE] SELF-HEAL: %s", reason)
    _append_sre({"ts": now, "action": "self_heal_start", "reason": reason})
    clear_outbound_queues()
    kill_zombie_processes()
    if any(x in reason for x in ("adb_listener_down", "adb_clicker_down", "ADB_MISSING")):
        reset_adb_tunnels()
    time.sleep(1)
    ok = restart_stack(reason)
    time.sleep(2)
    grp = recover_listener_group()
    _append_sre(
        {
            "ts": time.time(),
            "action": "self_heal_done",
            "reason": reason,
            "ok": ok,
            "listener_recovered": grp,
        }
    )
    return ok


def trigger_combat_heal(reason: str) -> bool:
    """稳态自愈：遵守冷却，避免风暴。"""
    return trigger_self_heal(reason, force=False)
