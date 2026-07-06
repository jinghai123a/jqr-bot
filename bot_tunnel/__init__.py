"""VMOS tunnel refresh — shared env I/O, SSH parse, ADB probe, pad resolve."""
from __future__ import annotations

from .adb_probe import adb_probe_port
from .env_io import load_env_file, parse_local_port, shell_env_line, write_tunnel_env
from .expire_schedule import (
    adb_expire_minutes,
    format_expire_status,
    in_maintenance_window,
    minutes_until_expire,
    next_maintenance_start,
    refresh_buffer_minutes,
    should_refresh_tunnel,
    should_refresh_urgent,
)
from .daemon import (
    DaemonConfig,
    build_daemon_sides,
    load_daemon_state,
    request_urgent_refresh,
    run_daemon_cycle,
    run_forever,
)
from .lock import acquire_refresh_lock
from .pad_resolve import android_major, resolve_pad_code
from .refresh import fetch_adb_with_backoff, reconnect_sides, refresh_side_credentials
from .ssh_parse import (
    parse_ssh_command,
    rewrite_adb_connect_port,
    rewrite_ssh_forward_port,
)

__all__ = [
    "adb_probe_port",
    "android_major",
    "adb_expire_minutes",
    "format_expire_status",
    "in_maintenance_window",
    "next_maintenance_start",
    "refresh_buffer_minutes",
    "acquire_refresh_lock",
    "fetch_adb_with_backoff",
    "load_env_file",
    "parse_local_port",
    "parse_ssh_command",
    "rewrite_adb_connect_port",
    "rewrite_ssh_forward_port",
    "reconnect_sides",
    "refresh_side_credentials",
    "resolve_pad_code",
    "minutes_until_expire",
    "should_refresh_urgent",
    "should_refresh_tunnel",
    "shell_env_line",
    "write_tunnel_env",
]
