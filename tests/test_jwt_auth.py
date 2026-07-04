"""JWT auth tests."""
from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from edge_brain.app import app
from edge_brain.jwt_auth import mint_service_token, verify_token


class JwtAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["EDGE_BRAIN_JWT_SECRET"] = "test-secret-for-jwt-auth-unit-tests"
        os.environ.pop("EDGE_BRAIN_AUTH_DISABLE", None)
        self.client = TestClient(app)
        self.jwt = mint_service_token(sub="test")
        self.h = {"Authorization": f"Bearer {self.jwt}"}

    def test_mint_and_verify(self) -> None:
        payload = verify_token(self.jwt)
        self.assertEqual(payload["sub"], "test")

    def test_rejects_plain_bearer(self) -> None:
        r = self.client.get("/edge/timeline", headers={"Authorization": "Bearer w49-edge-local"})
        self.assertEqual(r.status_code, 401)
        body = r.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "invalid token")

    def test_unauthorized_error_envelope(self) -> None:
        r = self.client.get("/edge/timeline")
        self.assertEqual(r.status_code, 401)
        body = r.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "unauthorized")

    def test_accepts_jwt(self) -> None:
        r = self.client.get("/edge/timeline", headers=self.h)
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
