"""Apply W49 manual OpenAPI tunnel creds for both sides (normalize to canonical ports)."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import json

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH
from bot_tunnel import (
    load_env_file,
    parse_ssh_command,
    rewrite_adb_connect_port,
    rewrite_ssh_forward_port,
    write_tunnel_env,
)

R = "/home/bot/55chat-bot"


def _canonical_ports() -> dict[str, str]:
    pads_path = ROOT / "config" / "vmos-pads.json"
    pads = json.loads(pads_path.read_text(encoding="utf-8")) if pads_path.exists() else {}
    bot_env = load_env_file(ROOT / "config" / "bot-start.env")
    return {
        "right": str(
            (pads.get("right") or {}).get("local_port")
            or bot_env.get("BOT_LISTENER_ADB_PORT", "58433")
        ),
        "left": str(
            (pads.get("left") or {}).get("local_port")
            or bot_env.get("BOT_CLICKER_ADB_PORT", "55612")
        ),
    }


def _side_meta() -> dict[str, dict]:
    ports = _canonical_ports()
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    return {
        "right": {
            "canonical": ports["right"],
            "bind": str((pads.get("right") or {}).get("match_egress_ip") or "195.114.193.237"),
            "tunnel": "tunnel-right.sh",
            "adb_p": "5038",
        },
        "left": {
            "canonical": ports["left"],
            "bind": str((pads.get("left") or {}).get("match_egress_ip") or "195.114.193.136"),
            "tunnel": "tunnel-left.sh",
            "adb_p": "5039",
        },
    }


def _side_from_env(side: str) -> tuple[str, str, str]:
    prefix = side.upper()
    ssh_cmd = (os.environ.get(f"{prefix}_SSH_COMMAND") or "").strip()
    ssh_pass = (os.environ.get(f"{prefix}_SSH_PASS") or "").strip()
    adb_cmd = (os.environ.get(f"{prefix}_ADB_COMMAND") or "").strip()
    if not ssh_cmd or not ssh_pass:
        raise SystemExit(f"需要环境变量 {prefix}_SSH_COMMAND / {prefix}_SSH_PASS")
    sides = _side_meta()
    if not adb_cmd:
        adb_cmd = f"adb connect localhost:{sides[side]['canonical']}"
    return ssh_cmd, ssh_pass, adb_cmd


def _write_env(side: str, td: Path) -> Path:
    cfg = _side_meta()[side]
    ssh_cmd, ssh_pass, adb_raw = _side_from_env(side)
    norm_ssh = rewrite_ssh_forward_port(ssh_cmd, cfg["canonical"])
    norm_adb = rewrite_adb_connect_port(adb_raw, cfg["canonical"])
    host, port, user = parse_ssh_command(norm_ssh)
    issued = datetime.now(tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    exp_mins = os.environ.get("BOT_VMOS_ADB_EXPIRE_MINUTES", "1440")
    env_path = td / f"tunnel-{side}.env"
    write_tunnel_env(
        env_path,
        cfg["canonical"],
        host,
        port,
        user,
        ssh_pass,
        ssh_command=norm_ssh,
        adb_command=norm_adb,
        expire_minutes=str(exp_mins),
        issued_at=issued,
        tunnel_bind_ip=cfg["bind"],
        header=f"# W49 manual OpenAPI — normalized LOCAL_PORT={cfg['canonical']}",
    )
    return env_path


def main() -> int:
    which = (os.environ.get("TUNNEL_SIDES") or "both").strip().lower()
    sides = ["right", "left"] if which == "both" else [which]
    side_meta = _side_meta()

    cfg = load_vps_config(ROOT)
    py = f"{R}/.venv/bin/python3"

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        with VpsSSH(cfg) as ssh:
            for rel in (
                "bot_tunnel/expire_schedule.py",
                "bot_tunnel/env_io.py",
                "bot_tunnel/refresh.py",
                "bot_tunnel/__init__.py",
                "scripts/vmos-refresh-tunnels.py",
            ):
                ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")

            for side in sides:
                env_path = _write_env(side, tdir)
                remote = f"{R}/config/tunnel-{side}.env"
                ssh.sftp_put(str(env_path), remote)
                ssh.run(f"chmod 600 {remote}", 10)
                print(f"uploaded tunnel-{side}.env -> {side_meta[side]['canonical']}")

            ssh.run("pkill -f vmos-refresh-tunnels.py 2>/dev/null || true", 10)
            ssh.run(f"rm -f {R}/logs/.vmos-refresh.lock", 8)

            for side in sides:
                port = side_meta[side]["canonical"]
                ssh.run(f"pkill -f 'ssh.*{port}:' 2>/dev/null || true", 10)
            ssh.run("sleep 2", 5)

            for side in sides:
                script = side_meta[side]["tunnel"]
                print(f">>> bash scripts/{script}")
                out = ssh.run(f"bash {R}/scripts/{script} 2>&1", 90)
                print(out[-1500:] if len(out) > 1500 else out)

            print(">>> reconnect-dual-adb")
            print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -15", 120))

            if os.environ.get("TUNNEL_SKIP_API_REFRESH", "").strip() not in ("1", "true", "yes"):
                print(">>> vmos-refresh --status (API expire after OpenAPI sync)")
                print(ssh.run(f"cd {R} && {py} scripts/vmos-refresh-tunnels.py --status 2>&1", 60))

                for side in sides:
                    print(
                        ssh.run(
                            f"cd {R} && timeout 120 {py} scripts/vmos-refresh-tunnels.py "
                            f"--side {side} 2>&1 | tail -8",
                            130,
                        )
                    )
            else:
                print(">>> skip vmos-refresh (TUNNEL_SKIP_API_REFRESH)")

            print(">>> verify")
            ports = side_meta["left"]["canonical"], side_meta["right"]["canonical"]
            print(ssh.run(f"ss -tlnp | grep -E '{ports[0]}|{ports[1]}' || echo NO_PORTS", 15))
            print(ssh.run("adb -P 5038 devices -l; adb -P 5039 devices -l", 20))

            print(">>> reload workers")
            print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -12", 150))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
