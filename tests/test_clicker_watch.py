"""Unit tests for bot_ops.clicker_watch."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot_ops.clicker_watch import count_chat_image_views, poll_image_send_evidence

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ui"


class CountChatImageViewsTests(unittest.TestCase):
    def test_fixture_counts_two_bubbles(self) -> None:
        xml = (FIXTURES / "chat_with_images.xml").read_text(encoding="utf-8")
        self.assertEqual(count_chat_image_views(xml), 2)

    def test_no_images(self) -> None:
        xml = (FIXTURES / "chat_no_images.xml").read_text(encoding="utf-8")
        self.assertEqual(count_chat_image_views(xml), 0)


class PollImageSendEvidenceTests(unittest.TestCase):
    def test_recent_success(self) -> None:
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
        log = f"[{ts}] 左机 UI 发图成功 rid=123\n"
        ev = poll_image_send_evidence(log, now=now)
        self.assertTrue(ev["log_ok"])

    def test_timeout_no_success(self) -> None:
        log = "[2020-01-01 00:00:00] 批量发图失败\n"
        ev = poll_image_send_evidence(log)
        self.assertFalse(ev["log_ok"])


if __name__ == "__main__":
    unittest.main()
