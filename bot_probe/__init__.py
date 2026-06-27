from . import events
from .constants import ALLOWED_PROBE_PATHS, DEFAULT_PROBE_PORT, MAX_PROBE_QUEUE_SIZE
from .server import ProbeHttpHandler, probe_server_started, start_probe_server

__all__ = [
    "ALLOWED_PROBE_PATHS",
    "DEFAULT_PROBE_PORT",
    "MAX_PROBE_QUEUE_SIZE",
    "ProbeHttpHandler",
    "drain_events",
    "events_pending",
    "probe_server_started",
    "start_probe_server",
]


def drain_events() -> list:
    return events.drain_events()


def events_pending() -> bool:
    return events.events_pending()
