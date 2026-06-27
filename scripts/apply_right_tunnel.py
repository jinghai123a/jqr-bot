#!/usr/bin/env python3
"""用 W49 提供的 VMOS SSH 凭证更新右机隧道并重连。"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_tunnel import write_tunnel_env  # noqa: E402

SSH_HOST, SSH_PORT, SSH_USER = "129.227.134.130", "1824", "s"
SSH_PASS = (
    "7n3WtyI0/OzhHtCCtPzFv0PugO5fo9HwbJl0F2pG1Z5uImxS9BtXtze5Cc67JH3sLxmw9ieFzKW4JTZ6fJPg8Pv"
    "+gC0nL+h57AKnSFG/z31EAXNdDPnR6NHmeXIQnc78e/QF2iLQFTOPF8LAhnbkkg/3YoXQYehPDSYOkRRAav5GIMGNLNgV5"
    "clml8UDHRyzHxjVZYf19s7mIZ6OkgzTDoaWbltiMdOg9tFCJmVkMQ=="
)
LOCAL_PORT = "60478"


def ssh() -> paramiko.SSHClient:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)
    return s


def run(cmd: str, t: int = 180) -> str:
    s = ssh()
    _, o, e = s.exec_command(cmd, timeout=t)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    s.close()
    return out


def upload_daemon() -> None:
    s = ssh()
    sf = s.open_sftp()
    for rel in (
        "bot_55chat_daemon.py",
        "scripts/recover_listener_now.py",
        "config/pinned-coords.json",
    ):
        p = ROOT / rel
        if p.is_file():
            sf.put(str(p), f"{R}/{rel}")
    sf.close()
    s.close()


def write_tunnel_env_remote() -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
        tmp_path = Path(tmp.name)
        write_tunnel_env(
            tmp_path,
            LOCAL_PORT,
            SSH_HOST,
            SSH_PORT,
            SSH_USER,
            SSH_PASS,
            header="# updated from VMOS panel (apply_right_tunnel.py)",
        )
        extra = (
            f"ADB_SERIAL=127.0.0.1:{LOCAL_PORT}\n"
            f"BOT_ID=bot-4\n"
            f"ROLE=LISTENER\n"
        )
        tmp_path.write_text(tmp_path.read_text(encoding="utf-8") + extra, encoding="utf-8")
    try:
        s = ssh()
        sftp = s.open_sftp()
        sftp.put(str(tmp_path), f"{R}/config/tunnel-right.env")
        s.exec_command(f"chmod 600 {R}/config/tunnel-right.env")
        sftp.close()
        s.close()
    finally:
        os.unlink(tmp_path)


def main() -> int:
    upload_daemon()
    write_tunnel_env_remote()
    print("=== stop old recover ===")
    print(run("pkill -f vmos_tunnel_recover.py; true").strip())

    print("=== tunnel-right ===")
    out = run(f"bash {R}/scripts/tunnel-right.sh 2>&1", 90)
    print(out.strip())

    adb = run("adb devices -l")
    print("=== adb ===\n", adb.strip())
    if f"127.0.0.1:{LOCAL_PORT}" not in adb or "device" not in adb.split(LOCAL_PORT)[1].split("\n")[0]:
        print("TUNNEL_FAIL", file=sys.stderr)
        return 1

    print("=== recover listener ===")
    rec = run(f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 150)
    print(rec.strip())

    daemon = run("pgrep -af bot_55chat_daemon || true")
    if "bot_55chat_daemon.py" not in daemon:
        print(run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -8", 120))
    else:
        print("daemon already running")

    print("=== diag ===")
    print(run(f"cd {R} && python3 scripts/vps_diag_now.py 2>&1 | head -45", 200))

    log = ROOT / "logs" / "autonomous_watch_live.txt"
    subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "autonomous_round_watch.py"), "--need", "2", "--max-min", "90", "--no-upload"],
        stdout=open(log, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
    )
    print("watch started")
    return 0 if "AFTER in_group=True" in rec else 1


if __name__ == "__main__":
    raise SystemExit(main())
