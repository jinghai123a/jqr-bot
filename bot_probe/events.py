"""Probe event queue."""
from __future__ import annotations

import queue
from typing import Any

from .constants import MAX_PROBE_QUEUE_SIZE

_PROBE_EVENTS: queue.Queue = queue.Queue(maxsize=MAX_PROBE_QUEUE_SIZE)


def enqueue_event(event: dict[str, Any]) -> None:
    _PROBE_EVENTS.put_nowait(event)


def drain_events() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while True:
        try:
            out.append(_PROBE_EVENTS.get_nowait())
        except queue.Empty:
            break
    return out


def events_pending() -> bool:
    return not _PROBE_EVENTS.empty()


def reset_events_for_tests() -> None:
    """Drain queue between unit tests."""
    drain_events()
