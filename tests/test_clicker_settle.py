"""左机内结算（BOT_CLICKER_SETTLE）角色路由。"""
from __future__ import annotations

import sys
import unittest
from unittest import mock

if "fcntl" not in sys.modules:
    sys.modules["fcntl"] = mock.MagicMock()

import bot_55chat_daemon as d  # noqa: E402


class ClickerSettleTests(unittest.TestCase):
    def test_clicker_settle_requires_send_images(self) -> None:
        with mock.patch.object(d, "CLICKER_SETTLE_ENABLED", True), mock.patch.object(
            d, "CLICKER_SEND_IMAGES", False,
        ):
            self.assertFalse(d.clicker_settle_enabled())

    def test_should_run_settlement_on_clicker_when_enabled(self) -> None:
        bot = {"id": "bot-3"}
        serial = "127.0.0.1:52840"
        with mock.patch.object(d, "CLICKER_SETTLE_ENABLED", True), mock.patch.object(
            d, "CLICKER_SEND_IMAGES", True,
        ), mock.patch.object(d, "is_clicker_bot", return_value=True), mock.patch.object(
            d, "is_clicker_serial", return_value=True,
        ):
            self.assertTrue(d.should_run_settlement(bot, serial))

    def test_should_run_settlement_on_listener_when_disabled(self) -> None:
        bot = {"id": "bot-4"}
        serial = "127.0.0.1:58433"
        with mock.patch.object(d, "CLICKER_SETTLE_ENABLED", False), mock.patch.object(
            d, "is_clicker_bot", return_value=False,
        ), mock.patch.object(d, "is_clicker_serial", return_value=False):
            self.assertTrue(d.should_run_settlement(bot, serial))

    def test_should_not_run_settlement_listener_when_clicker_settle(self) -> None:
        bot = {"id": "bot-4"}
        serial = "127.0.0.1:58433"
        with mock.patch.object(d, "CLICKER_SETTLE_ENABLED", True), mock.patch.object(
            d, "CLICKER_SEND_IMAGES", True,
        ), mock.patch.object(d, "is_clicker_bot", return_value=False), mock.patch.object(
            d, "is_clicker_serial", return_value=False,
        ):
            self.assertFalse(d.should_run_settlement(bot, serial))


if __name__ == "__main__":
    unittest.main()
