"""LISTENER 结算 → CLICKER 发图 → LISTENER 新一局：跨进程文件队列（双进程栈）。"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DIR_NAME = "capture_ipc"


def _root() -> Path:
    return Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))


def _base() -> Path:
    d = _root() / "data" / DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pending_dir() -> Path:
    d = _base() / "pending"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _done_dir() -> Path:
    d = _base() / "done"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inflight_dir() -> Path:
    d = _base() / "inflight"
    d.mkdir(parents=True, exist_ok=True)
    return d


def dual_capture_ipc() -> bool:
    return os.environ.get("BOT_DUAL_PROCESS", "0").lower() in ("1", "true", "yes")


def needs_capture_ipc(img_serial: str, listener_serial: str) -> bool:
    if not img_serial or not listener_serial:
        return False
    if img_serial.strip() == listener_serial.strip():
        return False
    try:
        from bot_ops.runtime import load_bot_runtime

        rt = load_bot_runtime()
        return _adb_port_from_serial(img_serial) == rt.clicker_adb_port
    except Exception:
        return dual_capture_ipc()


def _adb_port_from_serial(serial: str) -> str:
    s = (serial or "").strip()
    if ":" in s:
        return s.rsplit(":", 1)[-1]
    return s


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def pending_path_for_rid(rid: int) -> Path | None:
    if rid <= 0:
        return None
    path = _pending_dir() / f"{rid}.json"
    return path if path.is_file() else None


def has_pending_for_rid(rid: int) -> bool:
    return pending_path_for_rid(rid) is not None


def has_inflight_for_rid(rid: int) -> bool:
    if rid <= 0:
        return False
    return (_inflight_dir() / f"{rid}.json").is_file()


def capture_in_progress_for_rid(rid: int) -> bool:
    return has_pending_for_rid(rid) or has_inflight_for_rid(rid)


def clicker_capture_queue_busy() -> bool:
    """左机发图队列是否已有待处理/进行中任务（禁止并发入队）。"""
    try:
        purge_stale_inflight(90.0)
        return bool(any(_pending_dir().glob("*.json"))) or bool(
            any(_inflight_dir().glob("*.json"))
        )
    except OSError:
        return False


def mark_inflight(rid: int, payload: dict[str, Any] | None = None) -> None:
    if rid <= 0:
        return
    body: dict[str, Any] = {"round_id": rid, "ts": time.time(), "pid": os.getpid()}
    if payload:
        body["paths"] = len(payload.get("image_paths") or [])
    _atomic_write(_inflight_dir() / f"{rid}.json", body)


def purge_stale_inflight(max_age_sec: float = 120.0) -> int:
    """清除超时 inflight，避免失败 rid 永久阻塞结算重试。"""
    now = time.time()
    cleared = 0
    for path in list(_inflight_dir().glob("*.json")):
        try:
            rid = int(path.stem)
            data = json.loads(path.read_text(encoding="utf-8"))
            age = now - float(data.get("ts") or 0)
            if age >= max_age_sec and not has_pending_for_rid(rid):
                path.unlink(missing_ok=True)
                cleared += 1
                log.info("[capture-ipc] 清除 stale inflight rid=%s age=%.0fs", rid, age)
        except (ValueError, OSError, json.JSONDecodeError):
            try:
                path.unlink(missing_ok=True)
                cleared += 1
            except OSError:
                pass
    return cleared


def clear_inflight(rid: int) -> None:
    if rid <= 0:
        return
    try:
        (_inflight_dir() / f"{rid}.json").unlink(missing_ok=True)
    except OSError:
        pass


def _terminal_dir() -> Path:
    """永久结案标记（poll 消费 done 后仍阻止重复入队）。"""
    d = _base() / "terminal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def capture_terminal_for_rid(rid: int) -> bool:
    if rid <= 0:
        return False
    return (_terminal_dir() / f"{rid}.json").is_file()


def capture_done_for_rid(rid: int) -> bool:
    """左机已结案（成功或失败），禁止重复入队同一期。"""
    if rid <= 0:
        return False
    return capture_terminal_for_rid(rid) or (_done_dir() / f"{rid}.json").is_file()


def enqueue_capture_ipc(payload: dict[str, Any]) -> bool:
    rid = int(payload.get("round_id") or 0)
    if rid <= 0:
        return False
    if capture_done_for_rid(rid):
        log.info("[capture-ipc] 跳过已结案 rid=%s", rid)
        return False
    path = _pending_dir() / f"{rid}.json"
    if path.is_file() or has_inflight_for_rid(rid):
        log.info("[capture-ipc] 跳过重复入队 rid=%s", rid)
        return False
    if clicker_capture_queue_busy():
        log.info("[capture-ipc] 左机队列忙，推迟入队 rid=%s", rid)
        return False
    payload = {**payload, "ts": time.time(), "pid": os.getpid()}
    _atomic_write(path, payload)
    log.info("[capture-ipc] 入队 rid=%s paths=%d", rid, len(payload.get("image_paths") or []))
    return True


def claim_pending_captures() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(_pending_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            path.unlink(missing_ok=True)
            if data:
                rid = int(data.get("round_id") or 0)
                if rid > 0:
                    mark_inflight(rid, data)
                out.append(data)
        except Exception as ex:
            log.warning("[capture-ipc] 读取失败 %s: %s", path.name, ex)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return out


def mark_capture_done(
    settled_rid: int,
    *,
    images_ok: bool,
    open_job: dict[str, Any] | None = None,
) -> None:
    if settled_rid <= 0:
        return
    payload = {
        "settled_rid": settled_rid,
        "images_ok": images_ok,
        "open_job": open_job or {},
        "ts": time.time(),
        "pid": os.getpid(),
    }
    _atomic_write(_done_dir() / f"{settled_rid}.json", payload)
    _atomic_write(_terminal_dir() / f"{settled_rid}.json", payload)
    clear_inflight(settled_rid)
    log.info("[capture-ipc] done rid=%s ok=%s", settled_rid, images_ok)


def has_pending_captures() -> bool:
    try:
        return any(_pending_dir().glob("*.json"))
    except OSError:
        return False


def poll_capture_done() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(_done_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            path.unlink(missing_ok=True)
            if data:
                out.append(data)
        except Exception as ex:
            log.warning("[capture-ipc] done 读取失败 %s: %s", path.name, ex)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return out


def outbound_to_dict(job: Any) -> dict[str, Any]:
    return {
        "serial": job.serial,
        "bot_id": str((job.bot or {}).get("id") or ""),
        "text": job.text or "",
        "settings": dict(job.settings or {}),
        "input_xy": list(job.input_xy) if job.input_xy else None,
        "send_xy": list(job.send_xy) if job.send_xy else None,
        "group_ok": bool(job.group_ok),
        "prio": int(job.prio),
        "kind": job.kind or "",
        "round_id": int(job.round_id or 0),
    }


def dict_to_outbound(job: dict[str, Any], bot: dict, serial: str) -> Any:
    from bot_55chat_daemon import OutboundSend, SEND_PRIO_OPEN_AFTER_SETTLE

    return OutboundSend(
        serial,
        bot,
        str(job.get("text") or ""),
        dict(job.get("settings") or {}),
        tuple(job["input_xy"]) if job.get("input_xy") else None,
        tuple(job["send_xy"]) if job.get("send_xy") else None,
        group_ok=bool(job.get("group_ok")),
        prio=int(job.get("prio") or SEND_PRIO_OPEN_AFTER_SETTLE),
        kind=str(job.get("kind") or "open_after_settle"),
        round_id=int(job.get("round_id") or 0),
    )
