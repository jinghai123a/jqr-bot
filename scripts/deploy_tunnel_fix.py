#!/usr/bin/env python3
"""部署隧道自愈修复（强制 LF 换行，避免 Windows CRLF 搞坏 VPS bash）。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]

UPLOAD = (
    "bot_55chat_daemon.py",
    "scripts/reconnect-dual-adb.sh",
    "scripts/tunnel-heal.sh",
    "scripts/tunnel-left.sh",
    "scripts/tunnel-right.sh",
    "scripts/watch-adb-tunnels.sh",
    "scripts/vmos-dual-watchdog.sh",
    "scripts/vmos-refresh-tunnels.py",
    "scripts/vmos_api_client.py",
)


def upload_lf(sftp: paramiko.SFTPClient, local: Path, remote: str) -> None:
    data = local.read_bytes().replace(b"\r\n", b"\n")
    with sftp.open(remote, "wb") as f:
        f.write(data)


def main() -> None:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)

    def run(cmd: str, t: int = 180) -> str:
        _, o, e = s.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")

    sf = s.open_sftp()
    for rel in UPLOAD:
        p = ROOT / rel
        if p.is_file():
            upload_lf(sf, p, f"{R}/{rel}")
    sf.close()
    print("uploaded (LF)", len(UPLOAD), "files")
    run(f"chmod +x {R}/scripts/*.sh")

    # 凭证刷新：每 6h 一次（SSH 密码约 24h 过期，不能只靠 03:00）
    cron_patch = f"""
import subprocess
cur = subprocess.run(['crontab','-l'], capture_output=True, text=True)
lines = [ln for ln in (cur.stdout if cur.returncode==0 else '').splitlines() if ln.strip()]
keep = [ln for ln in lines if 'vmos-refresh-tunnels' not in ln and 'vmos-dual-watchdog' not in ln and 'watch-adb-tunnels' not in ln]
keep += [
 '0 */6 * * * flock -n /home/bot/55chat-bot/logs/.vmos-refresh.lock -c "cd {R} && python3 scripts/vmos-refresh-tunnels.py --reconnect >> logs/vmos-refresh.log 2>&1"',
 '*/2 * * * * {R}/scripts/vmos-dual-watchdog.sh',
 '*/15 * * * * {R}/scripts/watch-adb-tunnels.sh',
]
subprocess.run(['crontab','-'], input='\\n'.join(keep)+'\\n', text=True, check=True)
print('crontab ok')
"""
    run(f"python3 - <<'PY'\n{cron_patch}\nPY", 30)

    print("=== reconnect (per-side) ===")
    print(run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -25", 120))
    print(run("adb devices -l"))
    print(run(f"bash -n {R}/scripts/tunnel-left.sh && bash -n {R}/scripts/reconnect-dual-adb.sh && echo SYNTAX_OK"))
    print(run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -5", 120))
    s.close()


if __name__ == "__main__":
    main()
