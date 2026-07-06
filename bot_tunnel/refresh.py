"""VMOS OpenAPI tunnel refresh orchestration."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from datetime import datetime
from zoneinfo import ZoneInfo

from .adb_probe import adb_probe_port
from .env_io import load_env_file, parse_local_port, write_tunnel_env
from .expire_schedule import adb_expire_minutes
from .pad_resolve import resolve_pad_code
from .ssh_parse import parse_ssh_command, rewrite_adb_connect_port, rewrite_ssh_forward_port

SleepFn = Callable[[float], None]
RunSubprocess = Callable[..., subprocess.CompletedProcess[str]]


def _adb_expire_minutes() -> int:
    return adb_expire_minutes()


def fetch_adb_with_backoff(
    client: Any,
    pad_code: str,
    *,
    open_adb_first: bool = True,
    attempts: int = 12,
    sleep_fn: SleepFn = time.sleep,
    wait_open_adb_tasks: bool = True,
    wait_for_attempt: Callable[[int], float] | None = None,
) -> dict:
    """Retry get_adb with backoff; optionally openOnlineAdb first."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            if attempt:
                wait = (
                    wait_for_attempt(attempt)
                    if wait_for_attempt
                    else min(90, 8 * attempt)
                )
                sleep_fn(wait)
            if open_adb_first:
                try:
                    tasks = client.open_adb([pad_code])
                    if wait_open_adb_tasks:
                        client.wait_open_adb_tasks(tasks)
                except RuntimeError:
                    pass
            adb = client.get_adb(pad_code, enable=True, expire_minutes=_adb_expire_minutes(), retries=3)
            command = str(adb.get("command") or "")
            ssh_pass = str(adb.get("key") or "")
            if not command or not ssh_pass:
                raise RuntimeError("adb 接口未返回完整 command/key，需先 openOnlineAdb")
            return adb
        except Exception as exc:
            last_exc = exc
            if wait_for_attempt:
                print(f"  get_adb {attempt + 1}/{attempts}: {exc}", flush=True)
    raise last_exc or RuntimeError(f"get_adb failed for {pad_code}")


def refresh_side_credentials(
    side: str,
    cfg: dict[str, Any],
    client: Any,
    pads: list[dict],
    models: dict[str, dict],
    *,
    sleep_fn: SleepFn = time.sleep,
    probe_port: Callable[[str], bool] = adb_probe_port,
    max_attempts: int = 12,
) -> tuple[bool, str | None]:
    """
    Fetch adb for one side and write tunnel env.
    Returns (success, error_message).
    """
    code = resolve_pad_code(side, cfg, pads, models)
    port = str(cfg["local_port"])
    tunnel_file: Path = cfg["tunnel_file"]

    last_exc: Exception | None = None
    adb: dict = {}
    for attempt in range(max(1, max_attempts)):
        try:
            if attempt:
                sleep_fn(min(90, 15 * (attempt + 1)))
            adb = {}
            try:
                adb = client.get_adb(code, enable=True, expire_minutes=_adb_expire_minutes(), retries=2)
            except RuntimeError as exc:
                last_exc = exc
                print(f"[{side}] get_adb attempt {attempt + 1}: {exc}")
            command = str(adb.get("command") or "")
            ssh_pass = str(adb.get("key") or "")
            if not command or not ssh_pass:
                try:
                    tasks = client.open_adb([code])
                    client.wait_open_adb_tasks(tasks, timeout=90, poll_interval=2)
                except RuntimeError as exc:
                    print(f"[warn] openOnlineAdb {side}: {exc}")
                adb = client.get_adb(code, enable=True, expire_minutes=_adb_expire_minutes(), retries=2)
                command = str(adb.get("command") or "")
                ssh_pass = str(adb.get("key") or "")
            if not command or not ssh_pass:
                raise RuntimeError("adb 接口未返回完整 command/key，需先 openOnlineAdb")
            break
        except RuntimeError as exc:
            last_exc = exc
            print(f"[warn] refresh {side} attempt {attempt + 1}: {exc}")

    if not adb:
        if probe_port(port):
            print(f"[{side}] API busy but adb :{port} online — keep existing tunnel env")
            return True, None
        if tunnel_file.exists() and load_env_file(tunnel_file).get("SSH_PASS"):
            print(f"[{side}] API failed — keep existing {tunnel_file.name}, will try reconnect")
            return False, side
        print(f"[{side}] FATAL refresh: {last_exc}", flush=True)
        return False, side

    command = str(adb.get("command") or "")
    adb_cmd = str(adb.get("adb") or "")
    ssh_pass = str(adb.get("key") or "")
    host, ssh_port, user = parse_ssh_command(command)
    canonical = str(port)
    api_port = parse_local_port(command, adb_cmd, canonical)
    if api_port != canonical:
        print(f"[{side}] normalize OpenAPI local port {api_port} -> {canonical}")
    command = rewrite_ssh_forward_port(command, canonical)
    adb_cmd = rewrite_adb_connect_port(adb_cmd, canonical)
    bind_ip = str(cfg.get("tunnel_bind") or "").strip()
    exp_mins = _adb_expire_minutes()
    issued = datetime.now(tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    write_tunnel_env(
        tunnel_file,
        canonical,
        host,
        ssh_port,
        user,
        ssh_pass,
        ssh_command=command,
        adb_command=adb_cmd,
        expire_time=str(adb.get("expireTime") or ""),
        expire_minutes=str(exp_mins),
        issued_at=issued,
        tunnel_bind_ip=bind_ip,
    )
    print(
        f"[{side}] updated {tunnel_file.name} "
        f"port={canonical} host={host}:{ssh_port} expire={adb.get('expireTime')}",
        flush=True,
    )
    return True, None


def reconnect_sides(
    sides: dict[str, dict[str, Any]],
    root: Path,
    *,
    probe_port: Callable[[str], bool] = adb_probe_port,
    run_subprocess: RunSubprocess = subprocess.run,
) -> None:
    for side, cfg in sides.items():
        port = str(cfg["local_port"])
        if probe_port(port):
            continue
        script = "tunnel-right.sh" if side == "right" else "tunnel-left.sh"
        print(f"[reconnect] {side} via {script}")
        r = run_subprocess(
            ["bash", str(root / "scripts" / script)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
        )
        print(r.stdout.strip() or r.stderr.strip())
    run_subprocess(["adb", "devices", "-l"], check=False)
