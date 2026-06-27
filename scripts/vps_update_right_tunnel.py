#!/usr/bin/env python3
"""右机新 SSH 密钥 → 60478 隧道 → 重启 LISTENER。"""
from __future__ import annotations

import os

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
RIGHT = "127.0.0.1:60478"
SSH_KEY = (
    "6kyxWl7zzKmIocoT++Oi7wFQ0ppfA3OFLrz3KbF5o7CDoDIonRM3XmXrH8/2ggdNB/oSntUwdG3jYBbdFM29KgIaKrLQP"
    "+QZZacmDshhj3IS40cD+uKPl4JVhswizCFJHI/6pvlx+wR1643jDicnbGvYt5niLC5wL70FB2e4Dy+XOvQfylVrF+iBWO0NUWCxmLOi"
    "/n5gjqMtFgoLcVlAoh0IDL2l2b9OTuVXKskjPA=="
)


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 180) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode("utf-8", "replace")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)

    base = os.path.dirname(os.path.abspath(__file__))
    sftp = ssh.open_sftp()
    sftp.put(os.path.join(base, "_patch_right_tunnel.py"), f"{R}/scripts/_patch_right_tunnel.py")
    with sftp.file(f"{R}/secrets/adb_tunnel_key_right", "w") as f:
        f.write(SSH_KEY)
    sftp.close()

    print(run(ssh, f"python3 {R}/scripts/_patch_right_tunnel.py"))

    print(run(ssh, "pkill -f 'ssh.*60478:localhost' 2>/dev/null; pkill -f 'ssh.*54936:localhost' 2>/dev/null; sleep 2; true"))
    print("=== tunnel-right ===")
    print(run(ssh, f"bash {R}/scripts/tunnel-right.sh 2>&1"))
    print(run(ssh, f"adb connect {RIGHT}"))
    print(run(ssh, "adb devices -l"))

    dev = run(ssh, "adb devices -l")
    if "60478" not in dev or "device" not in dev.split("60478")[-1][:15]:
        print("FAIL: 右机仍离线")
        ssh.close()
        return

    print("=== restart bot ===")
    print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -25"))
    run(ssh, "sleep 12")

    print("=== recover ===")
    print(
        run(
            ssh,
            f"cd {R} && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group {RIGHT} 2>&1 | tail -12",
            timeout=120,
        )
    )

    print("=== listener check ===")
    print(
        run(
            ssh,
            f"tail -40 {R}/logs/bot.log | grep -E 'LISTENER|编排|target_group|sender|DEPLOY|ERROR|recover|监听' | tail -20",
        )
    )
    print(run(ssh, f"curl -s http://127.0.0.1:3000/api/bots | python3 -c \"import sys,json;print([{{'id':b.get('id'),'host':b.get('adbHost'),'st':b.get('status')}} for b in json.load(sys.stdin)])\""))
    ssh.close()


if __name__ == "__main__":
    main()
