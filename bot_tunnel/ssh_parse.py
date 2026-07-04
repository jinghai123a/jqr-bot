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


def rewrite_ssh_forward_port(command: str, canonical_port: str) -> str:
    """Normalize OpenAPI -L <ephemeral>:... to pinned LOCAL_PORT."""
    return re.sub(
        r"(-L\s+)\d+(:)",
        rf"\g<1>{canonical_port}\2",
        command,
        count=1,
    )


def rewrite_adb_connect_port(adb_command: str, canonical_port: str) -> str:
    """Normalize adb connect localhost:<ephemeral> to pinned port."""
    return re.sub(
        r"(localhost:|127\.0\.0\.1:)\d+",
        rf"\g<1>{canonical_port}",
        adb_command,
        count=1,
    )
