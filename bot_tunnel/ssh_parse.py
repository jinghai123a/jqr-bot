"""Parse VMOS OpenAPI SSH command strings."""
from __future__ import annotations

import re


def parse_ssh_command(command: str) -> tuple[str, str, str]:
    """Return (host, port, user) from VMOS SSH command (logging/validation only)."""
    port_m = re.search(r"-p\s+(\d+)", command)
    user_host_m = re.search(r"([\w-]+)@([\d.]+)", command)
    if not user_host_m:
        raise ValueError(f"无法解析 SSH command: {command!r}")
    user = user_host_m.group(1)
    host = user_host_m.group(2)
    port = port_m.group(1) if port_m else "1824"
    return host, port, user
