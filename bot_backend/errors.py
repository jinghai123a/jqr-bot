"""Typed errors for bot backend HTTP client (internal)."""
from __future__ import annotations


class BackendApiError(Exception):
    """Base error for backend API client internals."""


class BackendHttpError(BackendApiError):
    def __init__(self, status: int, path: str, body: str) -> None:
        self.status = status
        self.path = path
        self.body = body
        super().__init__(f"HTTP {status} {path}: {body}")


class BackendJsonError(BackendApiError):
    def __init__(self, path: str, raw: str) -> None:
        self.path = path
        self.raw = raw
        super().__init__(f"Invalid JSON from {path}: {raw[:500]}")
