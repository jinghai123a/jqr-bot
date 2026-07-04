"""Read canonical LISTENER/CLICKER ADB ports from config (local + VPS ops scripts)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def dual_adb_ports(root: Path | None = None) -> tuple[str, str]:
    """Return (listener_port, clicker_port) as strings."""
    root = root or ROOT
    listener = "58433"
    clicker = "55612"
    pads_path = root / "config" / "vmos-pads.json"
    if pads_path.is_file():
        pads = json.loads(pads_path.read_text(encoding="utf-8"))
        listener = str((pads.get("right") or {}).get("local_port") or listener)
        clicker = str((pads.get("left") or {}).get("local_port") or clicker)
    env = _parse_env(root / "config" / "bot-start.env")
    listener = env.get("BOT_LISTENER_ADB_PORT", listener)
    clicker = env.get("BOT_CLICKER_ADB_PORT", clicker)
    return listener, clicker


def port_device_online(out: str, port: str) -> bool:
    for line in out.splitlines():
        if port in line and "\tdevice" in line:
            return True
    return False


def dual_adb_online(out: str, listener_port: str, clicker_port: str) -> bool:
    return port_device_online(out, listener_port) and port_device_online(out, clicker_port)
