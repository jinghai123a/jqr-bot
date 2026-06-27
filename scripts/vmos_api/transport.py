"""HTTP transport with retry for VMOS Cloud API."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .errors import VmosHttpError, VmosJsonError, VmosResponseError
from .signer import VmosSigner


class VmosTransport:
    BASE = f"https://{VmosSigner.HOST}"
    BUSY_PATHS = ("/padApi/adb", "/padApi/openOnlineAdb", "/padApi/infos")

    def __init__(
        self,
        signer: VmosSigner,
        *,
        timeout: int = 60,
        urlopen: Callable[..., Any] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._signer = signer
        self.timeout = timeout
        self._urlopen = urlopen or urllib.request.urlopen
        self._sleep = sleep_fn or time.sleep

    def _max_retries(self, path: str, retries: int) -> int:
        if any(p in path for p in self.BUSY_PATHS):
            return max(retries, 8)
        return retries

    def post(self, path: str, payload: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any]:
        body = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
        last_err: Exception | None = None
        max_retries = self._max_retries(path, retries)
        for attempt in range(max_retries):
            req = urllib.request.Request(
                f"{self.BASE}{path}",
                data=body.encode("utf-8"),
                headers=self._signer.headers(body),
                method="POST",
            )
            try:
                with self._urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                http_err = VmosHttpError(exc.code, path, raw)
                last_err = RuntimeError(str(http_err))
                if exc.code >= 500 and attempt + 1 < max_retries:
                    self._sleep(min(30, 3 * (attempt + 1)))
                    continue
                raise last_err from http_err
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                json_err = VmosJsonError(path, raw)
                raise RuntimeError(str(json_err)) from json_err
            code = data.get("code")
            if code in (200, "200", 0, "0", None):
                return data
            msg = data.get("msg") or data.get("message") or ""
            resp_err = VmosResponseError(path, code, str(msg))
            last_err = RuntimeError(str(resp_err))
            if str(code) in ("500", "503") or "busy" in str(msg).lower():
                if attempt + 1 < max_retries:
                    self._sleep(min(30, 3 * (attempt + 1)))
                    continue
            raise last_err
        raise last_err or RuntimeError(f"API failed: {path}")
