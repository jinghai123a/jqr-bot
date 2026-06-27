"""Probe HTTP service constants."""
from __future__ import annotations

DEFAULT_PROBE_PORT = 3910
MAX_PROBE_QUEUE_SIZE = 800
ALLOWED_PROBE_PATHS = ("/event", "/api/probe/event")
