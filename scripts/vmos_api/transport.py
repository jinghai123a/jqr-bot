"""HTTP transport with retry for VMOS Cloud API."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

from .errors import VmosHttpError, VmosJsonError, VmosResponseError
from .signer import VmosSigner

_PROXY_KEYS = ("VMOS_API_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")


def normalize_proxy_url(proxy: str | None) -> str:
    """Return a usable http(s)/socks proxy URL or empty string."""
    raw = (proxy or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    if not parsed.hostname:
        return ""
    return raw


def mask_proxy_url(proxy: str) -> str:
    """Hide credentials for logs."""
    if not proxy:
        return ""
    return re.sub(r"(//)[^@/]+@", r"\1***@", proxy)


def proxy_from_env(extra: dict[str, str] | None = None) -> str:
    """Resolve proxy from env dict / os.environ (VMOS_API_PROXY first)."""
    import os

    merged: dict[str, str] = {k: v for k, v in os.environ.items() if k in _PROXY_KEYS}
    if extra:
        for key in _PROXY_KEYS:
            val = (extra.get(key) or "").strip()
            if val:
                merged[key] = val
    for key in _PROXY_KEYS:
        val = normalize_proxy_url(merged.get(key))
        if val:
            return val
    return ""


def build_proxy_urlopen(
    proxy: str,
    *,
    base_urlopen: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    """Wrap urllib urlopen to route api.vmoscloud.com via HTTP(S) proxy."""
    proxy = normalize_proxy_url(proxy)
    if not proxy:
        return base_urlopen or urllib.request.urlopen
    handlers: list[Any] = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})]
    if proxy.lower().startswith("socks"):
        try:
            import socks  # type: ignore[import-untyped]  # PySocks
        except ImportError as exc:
            raise RuntimeError("socks proxy requires: pip install PySocks") from exc
        _ = socks  # referenced by ProxyHandler when scheme is socks*
    opener = urllib.request.build_opener(*handlers)
    fallback = base_urlopen or urllib.request.urlopen

    def urlopen(req: urllib.request.Request, timeout: int = 60) -> Any:
        try:
            return opener.open(req, timeout=timeout)
        except urllib.error.URLError:
            return fallback(req, timeout=timeout)

    return urlopen


class VmosTransport:
    BASE = f"https://{VmosSigner.HOST}"
    BUSY_PATHS = ("/padApi/adb", "/padApi/openOnlineAdb", "/padApi/infos")

    def __init__(
        self,
        signer: VmosSigner,
        *,
        timeout: int = 60,
        proxy: str | None = None,
        urlopen: Callable[..., Any] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._signer = signer
        self.timeout = timeout
        self.proxy = normalize_proxy_url(proxy)
        base = urlopen or urllib.request.urlopen
        self._urlopen = build_proxy_urlopen(self.proxy, base_urlopen=base) if self.proxy else base
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
