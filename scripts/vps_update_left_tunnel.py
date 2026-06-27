#!/usr/bin/env python3
"""更新左机 SSH 密钥 + 52718 隧道并重连。"""
from __future__ import annotations

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
SSH_KEY = (
    "sGtdO68YuF4K17PhmHkGlod36+CTqbyZgJrFsglAVGNwMd6mWohbd6UokPyCjY91075eqSctuktDSUq0b7PSIfct1dmUlnR7X0hId6C+rsEoarYgmoe2Ehlfa2p97hlOMsc90r05YBK/17tZ+PNw9svn/jmvi05mz6TbJkWK1i85IyFAYkNcderwkT66o812UPWcGdtVM+xZvGzAGkkvwA1dpsKP7OpMOIUPniOcjOk="
)


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    return out + (f"\n{err}" if err.strip() else "")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)

    sftp = ssh.open_sftp()
    secret = f"{R}/secrets/adb_tunnel_key_left"
    with sftp.file(secret, "w") as f:
        f.write(SSH_KEY)
    sftp.close()

    patch = f"""
python3 - <<'PY'
from pathlib import Path
import re
root = Path("{R}")
key = (root / "secrets/adb_tunnel_key_left").read_text(encoding="utf-8").strip()
left = root / "config/tunnel-left.env"
lines = [
    "# clicker left machine (Hong Kong)",
    "LOCAL_PORT=52718",
    "SSH_HOST=98.98.37.2",
    "SSH_PORT=1824",
    "SSH_USER=s",
    f"SSH_PASS={{key}}",
    "ADB_SERIAL=127.0.0.1:52718",
    "BOT_ID=bot-3",
    "ROLE=CLICKER",
]
left.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
env = root / "config/bot-start.env"
if env.exists():
    t = env.read_text(encoding="utf-8")
    if re.search(r"^BOT_CLICKER_ADB_PORT=", t, re.M):
        t = re.sub(r"^BOT_CLICKER_ADB_PORT=.*", "BOT_CLICKER_ADB_PORT=52718", t, flags=re.M)
    else:
        t += "\\nBOT_CLICKER_ADB_PORT=52718\\n"
    env.write_text(t, encoding="utf-8")
print("tunnel-left patched port=52718")
PY
"""
    print(run(ssh, patch))

    print("=== kill old 52840 ssh if any ===")
    print(run(ssh, "pkill -f 'ssh.*52840:localhost' 2>/dev/null; pkill -f 'ssh.*52718:localhost' 2>/dev/null; sleep 1; true"))

    print("=== tunnel-left ===")
    print(run(ssh, f"bash {R}/scripts/tunnel-left.sh 2>&1"))
    print(run(ssh, "adb devices -l"))

    serial = "127.0.0.1:52718"
    if serial not in run(ssh, "adb devices"):
        print("52718 failed, try 52840 legacy")
        serial = "127.0.0.1:52840"

    print(f"=== probe 55M @ {serial} ===")
    print(run(ssh, f"adb -s {serial} shell monkey -p wuwu.d260608.t2200.vn7gh4kzd3 -c android.intent.category.LAUNCHER 1"))
    print(run(ssh, f"adb -s {serial} shell input tap 360 732"))
    print(
        run(
            ssh,
            f"cd {R} && python3 scripts/probe-55m-commit-content.py --serial {serial} 2>&1",
            timeout=90,
        )
    )

    ssh.close()


if __name__ == "__main__":
    main()
