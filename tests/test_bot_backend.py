"""Unit tests for bot backend HTTP client."""
from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_backend.bills import fetch_user_bills, record_bill  # noqa: E402
from bot_backend.transport import BackendApiTransport  # noqa: E402


class _MockResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _MockResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class BackendTransportTests(unittest.TestCase):
    def _transport_with_body(self, body: str) -> BackendApiTransport:
        def fake_urlopen(req: object, timeout: int = 10) -> _MockResponse:
            return _MockResponse(body)

        return BackendApiTransport("http://127.0.0.1:3000", urlopen=fake_urlopen)

    def test_get_success_json(self) -> None:
        t = self._transport_with_body('{"ok": true, "items": [1, 2]}')
        result = t.request("GET", "/api/users")
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["items"], [1, 2])

    def test_post_success_json(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req: object, timeout: int = 10) -> _MockResponse:
            captured["method"] = getattr(req, "method", None)
            captured["has_content_type"] = (
                getattr(req, "has_header", lambda _n: False)("Content-type")
                or "Content-type" in dict(getattr(req, "header_items", lambda: [])())
            )
            return _MockResponse('{"code": 200}')

        t = BackendApiTransport("http://127.0.0.1:3000", urlopen=fake_urlopen)
        result = t.request("POST", "/api/bills", {"a": 1})
        self.assertEqual(result["code"], 200)
        self.assertEqual(captured["method"], "POST")
        self.assertTrue(captured["has_content_type"])

    def test_get_empty_body_returns_none(self) -> None:
        t = self._transport_with_body("")
        result = t.request("GET", "/api/settings")
        self.assertIsNone(result)

    def test_invalid_json_raises(self) -> None:
        t = self._transport_with_body("not-json")
        with self.assertRaises(json.JSONDecodeError):
            t.request("GET", "/api/bots")


class BillsTests(unittest.TestCase):
    def test_record_bill_swallows_failure(self) -> None:
        logger = logging.getLogger("test.record_bill")
        transport = mock.Mock()
        transport.request.side_effect = RuntimeError("network down")
        with self.assertLogs(logger, level="WARNING") as cm:
            record_bill(
                transport,
                logger,
                "bot-4",
                "alice",
                "下注",
                -100,
                900,
                "1 100",
                "C001",
            )
        self.assertTrue(any("账单记录失败" in m for m in cm.output))

    def test_record_bill_posts_payload(self) -> None:
        logger = logging.getLogger("test.record_bill_ok")
        transport = mock.Mock()
        record_bill(
            transport,
            logger,
            "bot-4",
            "bob",
            "中奖",
            50.5,
            1050.25,
            "detail",
            "C002",
        )
        transport.request.assert_called_once()
        args = transport.request.call_args[0]
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "/api/bills")
        body = args[2]
        self.assertEqual(body["botId"], "bot-4")
        self.assertEqual(body["amount"], 50.5)

    def test_fetch_user_bills_success_list(self) -> None:
        transport = mock.Mock()
        transport.request.return_value = [{"type": "下注", "amount": -10}]
        rows = fetch_user_bills(transport, "bot-4", "alice", 5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "下注")

    def test_fetch_user_bills_non_list_returns_empty(self) -> None:
        transport = mock.Mock()
        transport.request.return_value = {"error": "x"}
        rows = fetch_user_bills(transport, "bot-4", "alice")
        self.assertEqual(rows, [])

    def test_fetch_user_bills_failure_returns_empty(self) -> None:
        transport = mock.Mock()
        transport.request.side_effect = OSError("refused")
        rows = fetch_user_bills(transport, "bot-4", "alice")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
