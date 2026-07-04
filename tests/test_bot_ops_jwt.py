"""bot_ops.auth.jwt 单元测试。"""
from __future__ import annotations

import os
import unittest

from bot_ops.auth.jwt import (
    JWTAuthError,
    JWTSecretMissingError,
    decode_token,
    encode_token,
    verify_token,
)


class BotOpsJwtTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["EDGE_BRAIN_JWT_SECRET"] = "unit-test-jwt-secret-not-hardcoded"
        os.environ.pop("JWT_SECRET", None)

    def tearDown(self) -> None:
        os.environ.pop("EDGE_BRAIN_JWT_SECRET", None)

    def test_encode_and_verify_roundtrip(self) -> None:
        token = encode_token(sub="bot-3", extra={"scope": "edge"})
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "bot-3")
        self.assertEqual(payload["scope"], "edge")

    def test_decode_alias(self) -> None:
        token = encode_token(sub="alias-test")
        self.assertEqual(decode_token(token)["sub"], "alias-test")

    def test_missing_secret_raises(self) -> None:
        os.environ.pop("EDGE_BRAIN_JWT_SECRET", None)
        with self.assertRaises(JWTSecretMissingError):
            encode_token(sub="x")

    def test_invalid_token_raises(self) -> None:
        with self.assertRaises(JWTAuthError):
            verify_token("not-a-jwt")


if __name__ == "__main__":
    unittest.main()
