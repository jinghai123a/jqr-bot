"""Edge Brain 持久状态（gates / settle-done）。"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _root() -> Path:
    root = Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
    d = root / "data" / "edge_brain"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return _root() / "state.json"


def load_state() -> dict[str, Any]:
    p = _state_path()
    if not p.is_file():
        return {"gates": {}, "settle_done": {}, "open_jobs": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"gates": {}, "settle_done": {}, "open_jobs": {}}


def save_state(state: dict[str, Any]) -> None:
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_state_path())


def mark_settle_done(
    period: int,
    *,
    images_ok: bool,
    open_rid: int = 0,
    open_text: str = "",
) -> dict[str, Any]:
    with _LOCK:
        st = load_state()
        key = str(period)
        st.setdefault("settle_done", {})[key] = {
            "images_ok": images_ok,
            "ts": time.time(),
        }
        gates = st.setdefault("gates", {})
        if images_ok:
            gates["open"] = True
            gates["open_rid"] = open_rid
            if open_text:
                st.setdefault("open_jobs", {})[key] = {
                    "open_rid": open_rid,
                    "text": open_text,
                    "ts": time.time(),
                }
        else:
            gates["open"] = False
        save_state(st)
        return st


def consume_open_job(period: int) -> dict[str, Any] | None:
    with _LOCK:
        st = load_state()
        job = (st.get("open_jobs") or {}).pop(str(period), None)
        save_state(st)
        return job


def get_gates() -> dict[str, Any]:
    with _LOCK:
        st = load_state()
        return dict(st.get("gates") or {})
