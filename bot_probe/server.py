"""Probe HTTP server."""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

from .constants import ALLOWED_PROBE_PATHS, DEFAULT_PROBE_PORT
from . import events

log = logging.getLogger(__name__)

_SERVER_STARTED = False
_SERVER_LOCK = threading.Lock()


class ProbeHttpHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        if self.path not in ALLOWED_PROBE_PATHS:
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            ev = json.loads(raw.decode("utf-8"))
            if isinstance(ev, dict):
                events.enqueue_event(ev)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        except Exception:
            self.send_response(400)
            self.end_headers()


def probe_server_started() -> bool:
    return _SERVER_STARTED


def start_probe_server(
    *,
    port: int = DEFAULT_PROBE_PORT,
    enabled: bool = True,
    on_started: Callable[[], None] | None = None,
) -> None:
    global _SERVER_STARTED
    if _SERVER_STARTED or not enabled:
        return

    def _serve() -> None:
        global _SERVER_STARTED
        try:
            srv = HTTPServer(("0.0.0.0", port), ProbeHttpHandler)
            with _SERVER_LOCK:
                _SERVER_STARTED = True
            if on_started:
                on_started()
            log.info(
                "探针 HTTP 监听 0.0.0.0:%d (adb reverse tcp:%d tcp:%d)",
                port,
                port,
                port,
            )
            srv.serve_forever()
        except OSError as ex:
            if getattr(ex, "errno", None) == 98:
                log.info("探针 HTTP 端口 %d 已被占用（已有实例在监听）", port)
                _SERVER_STARTED = True
            else:
                log.warning("探针 HTTP 启动失败: %s", ex)

    threading.Thread(target=_serve, name="probe-http", daemon=True).start()


def reset_server_state_for_tests() -> None:
    """Reset started flag between unit tests (server thread may still run)."""
    global _SERVER_STARTED
    _SERVER_STARTED = False
