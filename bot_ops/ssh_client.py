"""Paramiko SSH client wrapper for VPS operations."""
from __future__ import annotations

from typing import TYPE_CHECKING

import paramiko

if TYPE_CHECKING:
    from .config import VpsConfig


class VpsSSH:
    def __init__(self, config: VpsConfig) -> None:
        self.config = config
        self._client: paramiko.SSHClient | None = None

    def connect(self) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = {
            "hostname": self.config.host,
            "username": self.config.user,
            "timeout": 30,
        }
        if self.config.key_path:
            kwargs["key_filename"] = self.config.key_path
        else:
            kwargs["password"] = self.config.password
        client.connect(**kwargs)
        self._client = client

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> VpsSSH:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def client(self) -> paramiko.SSHClient:
        if self._client is None:
            raise RuntimeError("VpsSSH not connected")
        return self._client

    def run(self, cmd: str, timeout: int = 90) -> str:
        _, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        return (stdout.read() + stderr.read()).decode("utf-8", "replace")

    def sftp_get(self, remote: str, local: str) -> None:
        sf = self.client.open_sftp()
        try:
            sf.get(remote, local)
        finally:
            sf.close()

    def sftp_put(self, local: str, remote: str) -> None:
        sf = self.client.open_sftp()
        try:
            sf.put(local, remote)
        finally:
            sf.close()
