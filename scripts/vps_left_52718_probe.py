#!/usr/bin/env python3
"""用 W49 提供的 SSH 命令更新左机隧道(52718) + 55M 内 FlorisBoard 探针。"""
from __future__ import annotations

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
LEFT_OLD = "127.0.0.1:52840"
LEFT_NEW = "127.0.0.1:52718"


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 180) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    return out + (f"\n{err}" if err.strip() else "")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)

    patch = f"""
python3 - <<'PY'
from pathlib import Path
import re
root = Path("{R}")
left = root / "config/tunnel-left.env"
key = ""
for p in (root/"secrets/adb_tunnel_key_left", root/"secrets/adb_tunnel_key"):
    if p.exists():
        key = p.read_text(encoding="utf-8").strip()
        break
lines = []
for ln in left.read_text(encoding="utf-8").splitlines():
    if ln.startswith("LOCAL_PORT="):
        lines.append("LOCAL_PORT=52718")
    elif ln.startswith("ADB_SERIAL="):
        lines.append("ADB_SERIAL=127.0.0.1:52718")
    elif ln.startswith("SSH_HOST="):
        lines.append("SSH_HOST=98.98.37.2")
    elif ln.startswith("SSH_PORT="):
        lines.append("SSH_PORT=1824")
    elif ln.startswith("SSH_USER="):
        lines.append("SSH_USER=s")
    elif ln.startswith("SSH_PASS=") and key:
        lines.append(f"SSH_PASS={{key}}")
    else:
        lines.append(ln)
left.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
env = root / "config/bot-start.env"
if env.exists():
    t = env.read_text(encoding="utf-8")
    t2 = re.sub(r"^BOT_CLICKER_ADB_PORT=.*$", "BOT_CLICKER_ADB_PORT=52718", t, flags=re.M)
    if "BOT_CLICKER_ADB_PORT=" not in t2:
        t2 += "\\nBOT_CLICKER_ADB_PORT=52718\\n"
    env.write_text(t2, encoding="utf-8")
print(left.read_text().replace(key, "***") if key else left.read_text())
PY
"""
    print("=== patch tunnel-left -> 52718 ===")
    print(run(ssh, patch))

    print("=== reconnect left ===")
    print(run(ssh, f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -15"))
    print(run(ssh, "adb devices -l"))

    serial = LEFT_NEW if LEFT_NEW.split(":")[1] in run(ssh, "adb devices") else LEFT_OLD
    print(f"=== using serial {serial} ===")

    wuwu = "wuwu.d260608.t2200.vn7gh4kzd3"
    print(run(ssh, f"adb -s {serial} shell monkey -p {wuwu} -c android.intent.category.LAUNCHER 1"))
    print(run(ssh, "sleep 2"))
    print(run(ssh, f"adb -s {serial} shell input tap 360 732"))
    print(run(ssh, "sleep 1"))
    print(
        run(
            ssh,
            f"cd {R} && python3 scripts/probe-55m-commit-content.py --serial {serial} 2>&1",
            timeout=90,
        )
    )

    print("=== FlorisBoard grants check ===")
    print(
        run(
            ssh,
            f"adb -s {serial} shell dumpsys package dev.patrickgold.florisboard | grep -E 'granted=true|READ_MEDIA|CLIPBOARD' | head -15",
        )
    )

    ssh.close()


if __name__ == "__main__":
    main()
