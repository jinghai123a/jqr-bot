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
        import time

        _, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        chan = stdout.channel
        deadline = time.time() + max(timeout, 90)
        chunks: list[bytes] = []
        while time.time() < deadline:
            if chan.recv_ready():
                chunks.append(chan.recv(65535))
            if chan.recv_stderr_ready():
                chunks.append(chan.recv_stderr(65535))
            if chan.exit_status_ready():
                while chan.recv_ready():
                    chunks.append(chan.recv(65535))
                while chan.recv_stderr_ready():
                    chunks.append(chan.recv_stderr(65535))
                break
            time.sleep(0.2)
        return b"".join(chunks).decode("utf-8", "replace")

    def run_nohup(self, cmd: str, *, log_path: str, wait_sec: float = 5.0, poll_sec: float = 10.0, max_wait: float = 600.0) -> str:
        """Run long command in background; poll log until process exits."""
        import time

        escaped = cmd.replace("'", "'\"'\"'")
        self.run(
            f": > {log_path}; nohup bash -c '{escaped}' >> {log_path} 2>&1 </dev/null & echo started",
            15,
        )
        time.sleep(wait_sec)
        deadline = time.time() + max_wait
        last = ""
        while time.time() < deadline:
            running = self.run("pgrep -f 'vmos-refresh-tunnels.py' || echo 0", 15).strip()
            last = self.run(f"tail -50 {log_path} 2>/dev/null", 20)
            if running.endswith("0") or running == "0":
                break
            time.sleep(poll_sec)
        return last

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
