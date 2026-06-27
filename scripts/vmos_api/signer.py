"""HMAC-SHA256 request signing for VMOS Cloud API."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Callable


class VmosSigner:
    HOST = "api.vmoscloud.com"
    SERVICE = "armcloud-paas"
    ALGORITHM = "HMAC-SHA256"
    CONTENT_TYPE = "application/json;charset=UTF-8"

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.access_key = access_key.strip()
        self.secret_key = secret_key.strip()
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def sha256_hex(data: str) -> str:
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def sign(self, body: str, x_date: str) -> str:
        signed_headers = "content-type;host;x-content-sha256;x-date"
        canonical = (
            f"host:{self.HOST}\n"
            f"x-date:{x_date}\n"
            f"content-type:{self.CONTENT_TYPE}\n"
            f"signedHeaders:{signed_headers}\n"
            f"x-content-sha256:{self.sha256_hex(body)}"
        )
        short_date = x_date[:8]
        credential_scope = f"{short_date}/{self.SERVICE}/request"
        string_to_sign = "\n".join(
            (self.ALGORITHM, x_date, credential_scope, self.sha256_hex(canonical))
        )
        k_date = hmac.new(self.secret_key.encode(), short_date.encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_date, self.SERVICE.encode(), hashlib.sha256).digest()
        sign_key = hmac.new(k_service, b"request", hashlib.sha256).digest()
        return hmac.new(sign_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    def headers(self, body: str, *, x_date: str | None = None) -> dict[str, str]:
        if x_date is None:
            x_date = self._now_fn().strftime("%Y%m%dT%H%M%SZ")
        signature = self.sign(body, x_date)
        credential = f"{self.access_key}/{x_date[:8]}/{self.SERVICE}/request"
        authorization = (
            f"HMAC-SHA256 Credential={credential}, "
            f"SignedHeaders=content-type;host;x-content-sha256;x-date, "
            f"Signature={signature}"
        )
        return {
            "content-type": self.CONTENT_TYPE,
            "x-date": x_date,
            "x-host": self.HOST,
            "authorization": authorization,
        }
