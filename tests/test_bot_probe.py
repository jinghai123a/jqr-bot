"""Unit tests for bot probe HTTP service."""
from __future__ import annotations

import http.client
import io
import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_probe import events  # noqa: E402
from bot_probe.server import ProbeHttpHandler, reset_server_state_for_tests, start_probe_server  # noqa: E402


class ProbeEventsTests(unittest.TestCase):
    def setUp(self) -> None:
        events.reset_events_for_tests()

    def test_drain_empty(self) -> None:
        self.assertEqual(events.drain_events(), [])
        self.assertFalse(events.events_pending())

    def test_enqueue_and_drain(self) -> None:
        events.enqueue_event({"a": 1})
        self.assertTrue(events.events_pending())
        out = events.drain_events()
        self.assertEqual(out, [{"a": 1}])
        self.assertFalse(events.events_pending())


class ProbeServerTests(unittest.TestCase):
    def setUp(self) -> None:
        events.reset_events_for_tests()
        reset_server_state_for_tests()

    def test_start_disabled_does_not_mark_started(self) -> None:
        started: list[bool] = []

        def on_started() -> None:
            started.append(True)

        start_probe_server(port=0, enabled=False, on_started=on_started)
        time.sleep(0.05)
        self.assertEqual(started, [])

    def test_integration_paths_and_invalid_json(self) -> None:
        events.reset_events_for_tests()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        from http.server import HTTPServer

        class _OneShotHandler(ProbeHttpHandler):
            pass

        srv_holder: dict[str, HTTPServer] = {}

        def _serve_once() -> None:
            srv = HTTPServer(("127.0.0.1", port), _OneShotHandler)
            srv_holder["srv"] = srv
            srv.handle_request()

        for path, body, expect_status, expect_queue in (
            ("/event", json.dumps({"command": "1"}), 200, 1),
            ("/api/probe/event", json.dumps({"command": "余额"}), 200, 1),
            ("/unknown", "{}", 404, 0),
            ("/event", "not-json", 400, 0),
        ):
            events.reset_events_for_tests()
            th = threading.Thread(target=_serve_once, daemon=True)
            th.start()
            time.sleep(0.05)
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, expect_status, msg=f"path={path}")
            resp.read()
            conn.close()
            if "srv" in srv_holder:
                srv_holder["srv"].server_close()
            th.join(timeout=2)
            drained = events.drain_events()
            self.assertEqual(len(drained), expect_queue, msg=f"path={path}")

    def test_integration_post_to_free_port(self) -> None:
        events.reset_events_for_tests()
        reset_server_state_for_tests()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        srv_holder: dict[str, HTTPServer] = {}

        def _serve() -> None:
            srv = __import__("http.server", fromlist=["HTTPServer"]).HTTPServer(
                ("127.0.0.1", port), ProbeHttpHandler
            )
            srv_holder["srv"] = srv
            srv.handle_request()

        th = threading.Thread(target=_serve, daemon=True)
        th.start()
        time.sleep(0.05)

        payload = json.dumps({"sender": "test", "command": "ping"})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("POST", "/event", body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.read(), b"ok")
        conn.close()

        if "srv" in srv_holder:
            srv_holder["srv"].server_close()
        th.join(timeout=2)

        drained = events.drain_events()
        self.assertEqual(len(drained), 1)
        self.assertEqual(drained[0]["command"], "ping")


if __name__ == "__main__":
    unittest.main()
