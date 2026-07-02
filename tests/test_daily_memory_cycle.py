"""daily_memory_cycle 单元测试。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from bot_ops.daily_memory_cycle import (
    phase_vps_disk_clean,
    phase_vps_memory_spill,
    run_daily_memory_cycle,
)


class DailyMemoryCycleTests(unittest.TestCase):
    def test_vps_disk_then_spill(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data" / "captures").mkdir(parents=True)
            stale = root / "data" / "captures" / "old.png"
            stale.write_bytes(b"x")
            spill_old = root / "data" / "disk-spill" / "20000101"
            spill_old.mkdir(parents=True)
            (spill_old / "a.txt").write_text("old", encoding="utf-8")

            disk = phase_vps_disk_clean(root)
            self.assertEqual(disk["phase"], "disk_clean")
            self.assertGreaterEqual(disk.get("spill_dirs_removed", 0), 1)

            tmp = os.path.join(td, "tess_x.png")
            # use /tmp pattern - create in tmp via env
            import glob as g

            import tempfile as tf

            with tf.NamedTemporaryFile(
                prefix="tess_", suffix=".png", delete=False, dir=tf.gettempdir()
            ) as f:
                f.write(b"t")
                tmp_path = f.name
            try:
                spill = phase_vps_memory_spill(root)
                self.assertEqual(spill["phase"], "memory_spill")
                self.assertGreaterEqual(spill["files_moved"], 0)
            finally:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)

    def test_run_cycle_structure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            report = run_daily_memory_cycle(root)
            self.assertTrue(report.get("ok"))
            self.assertEqual(len(report["phases"]), 2)
            self.assertIn("mid_cache.json", report["preserve"])


if __name__ == "__main__":
    unittest.main()
