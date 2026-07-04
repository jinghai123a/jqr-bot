"""capture_ipc 跨进程结算图队列。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot_ops import capture_ipc as ci


class CaptureIpcTests(unittest.TestCase):
    def test_enqueue_claim_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(ci, "_root", return_value=root):
                ci.enqueue_capture_ipc({
                    "round_id": 99,
                    "image_paths": ["/tmp/a.png"],
                    "clicker_serial": "127.0.0.1:52840",
                    "open_job": {"text": "新一局", "round_id": 100},
                })
                claimed = ci.claim_pending_captures()
                self.assertEqual(len(claimed), 1)
                self.assertEqual(claimed[0]["round_id"], 99)
                self.assertTrue(ci.has_inflight_for_rid(99))
                ci.mark_capture_done(99, images_ok=True)
                self.assertFalse(ci.has_inflight_for_rid(99))

    def test_inflight_cleared_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(ci, "_root", return_value=root):
                ci.enqueue_capture_ipc({"round_id": 7, "image_paths": ["/a.png"], "clicker_serial": "x"})
                ci.claim_pending_captures()
                ci.mark_capture_done(7, images_ok=False)
                self.assertFalse(ci.has_inflight_for_rid(7))
                self.assertTrue(ci.capture_done_for_rid(7))

    def test_enqueue_skips_after_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(ci, "_root", return_value=root):
                ci.enqueue_capture_ipc({"round_id": 9, "image_paths": ["/a.png"], "clicker_serial": "x"})
                ci.claim_pending_captures()
                ci.mark_capture_done(9, images_ok=False)
                self.assertTrue(ci.capture_terminal_for_rid(9))
                ci.poll_capture_done()
                self.assertFalse((root / "data" / ci.DIR_NAME / "done" / "9.json").exists())
                self.assertTrue(ci.capture_done_for_rid(9))
                self.assertFalse(ci.enqueue_capture_ipc({
                    "round_id": 9,
                    "image_paths": ["/a.png"],
                    "clicker_serial": "x",
                }))

    def test_enqueue_skips_after_done(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(ci, "_root", return_value=root):
                ci.enqueue_capture_ipc({"round_id": 8, "image_paths": ["/a.png"], "clicker_serial": "x"})
                ci.claim_pending_captures()
                ci.mark_capture_done(8, images_ok=False)
                self.assertFalse(ci.enqueue_capture_ipc({
                    "round_id": 8,
                    "image_paths": ["/a.png"],
                    "clicker_serial": "x",
                }))

    def test_purge_stale_inflight(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(ci, "_root", return_value=root):
                ci.enqueue_capture_ipc({"round_id": 7, "image_paths": ["/a.png"], "clicker_serial": "x"})
                ci.claim_pending_captures()
                inflight = root / "data" / ci.DIR_NAME / "inflight" / "7.json"
                data = __import__("json").loads(inflight.read_text(encoding="utf-8"))
                data["ts"] = __import__("time").time() - 200
                inflight.write_text(__import__("json").dumps(data), encoding="utf-8")
                n = ci.purge_stale_inflight(120.0)
                self.assertEqual(n, 1)
                self.assertFalse(ci.has_inflight_for_rid(7))

    def test_enqueue_skips_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(ci, "_root", return_value=root):
                payload = {
                    "round_id": 99,
                    "image_paths": ["/tmp/a.png"],
                    "clicker_serial": "127.0.0.1:52840",
                }
                self.assertTrue(ci.enqueue_capture_ipc(payload))
                self.assertFalse(ci.enqueue_capture_ipc(payload))
                self.assertTrue(ci.capture_in_progress_for_rid(99))

    def test_enqueue_defers_when_queue_busy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(ci, "_root", return_value=root):
                self.assertTrue(ci.enqueue_capture_ipc({
                    "round_id": 10,
                    "image_paths": ["/a.png"],
                    "clicker_serial": "127.0.0.1:52840",
                }))
                ci.claim_pending_captures()
                self.assertFalse(ci.enqueue_capture_ipc({
                    "round_id": 11,
                    "image_paths": ["/b.png"],
                    "clicker_serial": "127.0.0.1:52840",
                }))
                self.assertFalse(ci.has_pending_for_rid(11))


if __name__ == "__main__":
    unittest.main()
