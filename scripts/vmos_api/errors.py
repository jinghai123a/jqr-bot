"""VMOS API typed errors (internal; public API still raises RuntimeError)."""
from __future__ import annotations


class VmosApiError(Exception):
    """Base error for VMOS API client internals."""


class VmosHttpError(VmosApiError):
    def __init__(self, status: int, path: str, body: str) -> None:
        self.status = status
        self.path = path
        self.body = body
        super().__init__(f"HTTP {status} {path}: {body}")


class VmosResponseError(VmosApiError):
    def __init__(self, path: str, code: object, msg: str) -> None:
        self.path = path
        self.code = code
        self.msg = msg
        super().__init__(f"API error {path} code={code} msg={msg}")


class VmosJsonError(VmosApiError):
    def __init__(self, path: str, raw: str) -> None:
        self.path = path
        self.raw = raw
        super().__init__(f"Invalid JSON from {path}: {raw[:500]}")
