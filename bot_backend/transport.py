"""HTTP transport for 55Chat control panel backend API."""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable


class BackendApiTransport:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: int = 10,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._urlopen = urlopen or urllib.request.urlopen

    def request(self, method: str, path: str, body: Any = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with self._urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
