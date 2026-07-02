"""ephemeral_burn 单元测试。"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot_ops.ephemeral_burn import burn_capture_tree, burn_paths


class EphemeralBurnTests(unittest.TestCase):
    def test_burn_paths_removes_png(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "trade_1.png")
            with open(p, "wb") as f:
                f.write(b"x")
            self.assertEqual(burn_paths([p]), 1)
            self.assertFalse(os.path.isfile(p))

    def test_burn_capture_tree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fp = os.path.join(td, "pc28_1.png")
            with open(fp, "wb") as f:
                f.write(b"x")
            n = burn_capture_tree(td)
            self.assertGreaterEqual(n, 1)
            self.assertFalse(os.path.isfile(fp))


if __name__ == "__main__":
    unittest.main()
