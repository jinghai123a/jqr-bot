"""Tunnel env file read/write — single source for OpenAPI adb response format."""
from __future__ import annotations

import os
import re
from pathlib import Path


def load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def shell_env_line(key: str, value: str) -> str:
    """Write KEY=value for tunnel env; command/adb fields must be quoted."""
    if not value:
        return f"{key}="
    if key in ("VMOS_SSH_COMMAND", "VMOS_ADB_COMMAND") or re.search(r"[\s#'\"\\]", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{escaped}"'
    return f"{key}={value}"


def parse_local_port(ssh_command: str, adb_command: str, fallback: str) -> str:
    m = re.search(r"-L\s+(\d+):", ssh_command)
    if m:
        return m.group(1)
    m = re.search(r"localhost:(\d+)", adb_command)
    if m:
        return m.group(1)
    return fallback


def write_tunnel_env(
    path: Path,
    local_port: str,
    ssh_host: str,
    ssh_port: str,
    ssh_user: str,
    ssh_pass: str,
    *,
    ssh_command: str = "",
    adb_command: str = "",
    expire_time: str = "",
    expire_minutes: str = "",
    issued_at: str = "",
    tunnel_bind_ip: str = "",
    header: str = "# auto-updated by vmos-refresh-tunnels.py — VMOS OpenAPI padApi/adb 原文",
) -> None:
    """Persist OpenAPI command/adb (local -L / adb connect 已归一化到 LOCAL_PORT)。"""
    lines = [
        header,
        "# 文档: https://cloud.vmoscloud.com/vmoscloud/doc/zh/server/OpenAPI.html",
    ]
    if tunnel_bind_ip:
        lines.append(shell_env_line("TUNNEL_SSH_BIND_IP", tunnel_bind_ip))
    lines.extend([
        shell_env_line("LOCAL_PORT", local_port),
        shell_env_line("VMOS_SSH_COMMAND", ssh_command.strip()),
        shell_env_line("VMOS_ADB_COMMAND", adb_command.strip()),
        shell_env_line("SSH_HOST", ssh_host),
        shell_env_line("SSH_PORT", ssh_port),
        shell_env_line("SSH_USER", ssh_user),
        shell_env_line("SSH_PASS", ssh_pass),
        shell_env_line("EXPIRE_TIME", expire_time),
        shell_env_line("EXPIRE_MINUTES", expire_minutes),
        shell_env_line("ISSUED_AT", issued_at),
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + "\n"
    path.write_bytes(content.encode("utf-8"))
    os.chmod(path, 0o600)
