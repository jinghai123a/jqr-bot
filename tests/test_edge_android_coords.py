"""edge_android 坐标与 pinned-coords 同步测试。"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EdgeAndroidCoordSyncTests(unittest.TestCase):
    def test_sync_matches_pinned(self) -> None:
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "sync_edge_android_coords.py")], cwd=ROOT)
        pinned = json.loads((ROOT / "config" / "pinned-coords.json").read_text(encoding="utf-8"))
        left = json.loads((ROOT / "edge_android" / "settle-left" / "edge_config.json").read_text(encoding="utf-8"))
        right = json.loads((ROOT / "edge_android" / "listener-right" / "edge_config.json").read_text(encoding="utf-8"))
        pc, pl = pinned["clicker"], pinned["listener"]
        self.assertEqual(left["coords"]["gallery_check_top3"], pc["gallery_check_top3"])
        self.assertEqual(left["coords"]["gallery_batch_send"], pc["gallery_batch_send"])
        self.assertEqual(left["coords"]["attach_image_bottom"], pc["attach_image_bottom"])
        self.assertEqual(right["coords"]["send"], pl["send"])


if __name__ == "__main__":
    unittest.main()
