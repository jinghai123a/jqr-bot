"""VPS operations — SSH, health checks, watch, acceptance, live verify."""
from __future__ import annotations

from .acceptance import run_verify_dual_brain
from .checks import (
    adb_online,
    adb_port_online,
    daemon_running,
    env_map,
    in_group_chat,
    log_ts,
    recent_log_matches,
)
from .config import VpsConfig, load_vps_config
from .live import run_live_verify
from .report import CheckResult, emit_json, emit_text, exit_code
from .ssh_client import VpsSSH
from .watch import run_watch_cycle
from . import clicker_watch

__all__ = [
    "CheckResult",
    "VpsConfig",
    "VpsSSH",
    "adb_online",
    "adb_port_online",
    "daemon_running",
    "emit_json",
    "emit_text",
    "env_map",
    "exit_code",
    "in_group_chat",
    "load_vps_config",
    "log_ts",
    "recent_log_matches",
    "run_live_verify",
    "run_verify_dual_brain",
    "run_watch_cycle",
    "clicker_watch",
]
