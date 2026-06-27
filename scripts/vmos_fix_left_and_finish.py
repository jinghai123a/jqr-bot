#!/usr/bin/env python3
"""修复左机 tunnel-left.env 端口 + 同步 SSH 密钥，并完成剩余部署。"""
import paramiko
import time

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"


def run(ssh, cmd, timeout=300):
    print(f">>> {cmd[:100]}")
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    if out.strip():
        print(out[:4000])
    if err.strip():
        print("[stderr]", err[:800])
    return out


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)

    # 左机端口 52840 + 从 secrets 同步 SSH 密码
    run(ssh, f"""
python3 - <<'PY'
from pathlib import Path
root = Path("{R}")
left = root / "config/tunnel-left.env"
key = (root / "secrets/adb_tunnel_key").read_text(encoding="utf-8").strip()
if not key and (root / "secrets/adb_tunnel_key_left").exists():
    key = (root / "secrets/adb_tunnel_key_left").read_text(encoding="utf-8").strip()
lines = []
for ln in left.read_text(encoding="utf-8").splitlines():
    if ln.startswith("LOCAL_PORT="):
        lines.append("LOCAL_PORT=52840")
    elif ln.startswith("SSH_PASS="):
        lines.append(f"SSH_PASS={{key}}")
    elif ln.startswith("ADB_SERIAL="):
        lines.append("ADB_SERIAL=127.0.0.1:52840")
    else:
        lines.append(ln)
left.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
print("tunnel-left.env patched")
PY
""")

    run(ssh, f"grep -E 'LOCAL_PORT|ADB_SERIAL' {R}/config/tunnel-left.env")
    run(ssh, f"bash {R}/scripts/reconnect-dual-adb.sh", timeout=120)
    run(ssh, f"bash {R}/scripts/setup-cloud-clipboard.sh", timeout=600)

    # cron + systemd
    run(ssh, f"""
(crontab -l 2>/dev/null | grep -v '54936\\|58851\\|55chat-bot/vmos-dual' || true
 echo '*/2 * * * * /home/bot/55chat-bot/scripts/vmos-dual-watchdog.sh'
 echo '0 3 * * * cd /home/bot/55chat-bot && python3 scripts/vmos-refresh-tunnels.py --reconnect >> logs/vmos-refresh.log 2>&1'
) | crontab -
""")

    run(ssh, """
cat > /etc/systemd/system/vmos-dual-watchdog.service <<'EOF'
[Unit]
Description=VMOS dual ADB watchdog
After=network-online.target
[Service]
Type=oneshot
ExecStart=/home/bot/55chat-bot/scripts/vmos-dual-watchdog.sh
EOF
cat > /etc/systemd/system/vmos-dual-watchdog.timer <<'EOF'
[Unit]
Description=Check dual ADB every 2 minutes
[Timer]
OnBootSec=90s
OnUnitActiveSec=2min
Persistent=true
Unit=vmos-dual-watchdog.service
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload && systemctl enable --now vmos-dual-watchdog.timer
""")

    run(ssh, f"cd {R} && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group 127.0.0.1:54936", timeout=120)
    run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh", timeout=90)
    time.sleep(6)
    run(ssh, "adb devices -l; crontab -l; systemctl is-active vmos-dual-watchdog.timer")
    run(ssh, f"tail -n 20 {R}/logs/clipboard-setup.log 2>/dev/null || true")
    run(ssh, f"tail -n 25 {R}/logs/bot.log")
    ssh.close()


if __name__ == "__main__":
    main()
