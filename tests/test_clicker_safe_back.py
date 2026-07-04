"""左机 clicker_safe_back 不得在目标群聊内误触 header 返回。"""
from __future__ import annotations

import sys
import unittest
from unittest import mock

if "fcntl" not in sys.modules:
    sys.modules["fcntl"] = mock.MagicMock()

import bot_55chat_daemon as d  # noqa: E402


class ClickerSafeBackTests(unittest.TestCase):
    def test_skips_header_back_in_target_group_with_recover_reason(self) -> None:
        serial = "127.0.0.1:52840"
        with mock.patch.object(d, "is_clicker_serial", return_value=True), mock.patch.object(
            d, "is_group_chat_activity", return_value=True,
        ), mock.patch.object(d, "_verify_gallery_picker_open_serial", return_value=False), mock.patch.object(
            d, "_verify_attach_menu_open_serial", return_value=False), mock.patch.object(
            d, "tap_header_back",
        ) as back, mock.patch.object(d, "dismiss_soft_keyboard") as kb:
            d.clicker_safe_back(serial, reason="回群 step=1")
            back.assert_not_called()
            kb.assert_called_once()

    def test_skips_header_back_for_gallery_reason_when_picker_closed(self) -> None:
        serial = "127.0.0.1:52840"
        with mock.patch.object(d, "is_clicker_serial", return_value=True), mock.patch.object(
            d, "is_group_chat_activity", return_value=True,
        ), mock.patch.object(d, "_verify_gallery_picker_open_serial", return_value=False), mock.patch.object(
            d, "_verify_attach_menu_open_serial", return_value=False), mock.patch.object(
            d, "tap_header_back",
        ) as back, mock.patch.object(d, "dismiss_soft_keyboard") as kb:
            d.clicker_safe_back(serial, reason="相册退一层(gallery_send)")
            back.assert_not_called()
            kb.assert_called_once()

    def test_allows_header_back_for_wrong_chat(self) -> None:
        serial = "127.0.0.1:52840"
        with mock.patch.object(d, "is_clicker_serial", return_value=True), mock.patch.object(
            d, "is_group_chat_activity", return_value=True,
        ), mock.patch.object(d, "_verify_gallery_picker_open_serial", return_value=False), mock.patch.object(
            d, "_verify_attach_menu_open_serial", return_value=False), mock.patch.object(
            d, "tap_header_back",
        ) as back, mock.patch.object(d, "dismiss_soft_keyboard"):
            d.clicker_safe_back(serial, reason="退出wrong_chat")
            back.assert_called_once()


if __name__ == "__main__":
    unittest.main()
