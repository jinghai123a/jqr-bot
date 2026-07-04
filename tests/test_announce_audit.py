"""群公告 OUT/IN 气泡分类测试。"""
from __future__ import annotations

import unittest

from bot_ops.announce_audit import (
    classify_bubble_side,
    extract_announce_bubbles,
    summarize_bubbles,
)


class AnnounceAuditTests(unittest.TestCase):
    def test_classify_outgoing_right_side(self) -> None:
        self.assertEqual(classify_bubble_side(500, 720), "OUT")

    def test_classify_incoming_left_side(self) -> None:
        self.assertEqual(classify_bubble_side(200, 720), "IN")

    def test_extract_and_summarize(self) -> None:
        nodes = [
            ("【1期】 新的一局开始", 80, 100, 300, 200),
            ("【2期】 已封盘", 520, 300, 680, 400),
        ]
        bubbles = extract_announce_bubbles(nodes, 720)
        summary = summarize_bubbles(bubbles)
        self.assertEqual(summary["in_count"], 1)
        self.assertEqual(summary["out_count"], 1)
        self.assertTrue(summary["bot_sent_evidence"])


if __name__ == "__main__":
    unittest.main()
