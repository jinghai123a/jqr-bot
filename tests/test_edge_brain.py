"""Edge Brain API 测试。"""
from __future__ import annotations

import base64
import io
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from edge_brain.app import app
from edge_brain.jwt_auth import mint_service_token
from w49_core import timing as timing_mod
from w49_render.png_bundle import build_settle_images


class EdgeBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        os.environ["EDGE_BRAIN_JWT_SECRET"] = "test-secret-for-jwt-auth-unit-tests"
        self.client = TestClient(app)
        token = mint_service_token(sub="test-edge-brain")
        self.h = {"Authorization": f"Bearer {token}"}

    def test_health(self) -> None:
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ok"], "true")

    def test_timeline(self) -> None:
        r = self.client.get("/edge/timeline", headers=self.h)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("rid", body)
        self.assertIn("windows", body)

    def test_settle_bundle_and_done(self) -> None:
        draw = {
            "round_id": 999001,
            "n1": 1,
            "n2": 2,
            "n3": 3,
            "final_result": 6,
            "opentime": "2026-06-01 12:00:00",
        }
        with mock.patch("edge_brain.app.draw_mod.fetch_28run_recent", return_value={"recent_results": []}), mock.patch(
            "edge_brain.app.draw_mod.find_draw_for_round", return_value=draw,
        ), mock.patch("edge_brain.app.fetch_trade_flow", return_value={"rows": [], "mock": True}):
            r = self.client.get("/settle-bundle?period=999001", headers=self.h)
            self.assertEqual(r.status_code, 200)
            bundle = r.json()
            self.assertEqual(len(bundle["images"]), 3)
            for img in bundle["images"]:
                raw = base64.standard_b64decode(img["b64"])
                self.assertGreater(len(raw), 100)
            done = self.client.post(
                "/settle-done",
                headers=self.h,
                json={"period": 999001, "images_ok": True, "device": "test"},
            )
            self.assertEqual(done.status_code, 200)
            self.assertTrue(done.json()["gates"]["open"])
            job = self.client.get("/edge/open-job", headers=self.h)
            self.assertEqual(job.status_code, 200)
            body = job.json()
            self.assertIn("open_text", body)
            self.assertIn("999002", body["open_text"])
            self.assertIn("新的一局", body["open_text"])

    def test_settle_bundle_not_found_envelope(self) -> None:
        with mock.patch("edge_brain.app.draw_mod.fetch_28run_recent", return_value={"recent_results": []}), mock.patch(
            "edge_brain.app.draw_mod.find_draw_for_round", return_value=None,
        ):
            r = self.client.get("/settle-bundle?period=1", headers=self.h)
            self.assertEqual(r.status_code, 404)
            body = r.json()
            self.assertFalse(body["success"])
            self.assertIn("draw not found", body["error"])

    def test_pillow_bundle(self) -> None:
        draw = {"n1": 1, "n2": 2, "n3": 3, "final_result": 6, "opentime": "x"}
        imgs = build_settle_images(1, draw, {"rows": []})
        self.assertEqual([x["kind"] for x in imgs], ["pc28", "mark6", "flow"])
        self.assertTrue(all(x["source"] == "pillow_fallback" for x in imgs))

    def test_build_timeline_has_ms(self) -> None:
        tl = timing_mod.build_timeline()
        self.assertGreater(tl["server_ts"], 0)
        self.assertIn("warn", tl["windows"])


if __name__ == "__main__":
    unittest.main()
