#!/usr/bin/env python3
"""右机隧道：强制 IPv4 (-4) 连接。"""
import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
KEY = (
    "6kyxWl7zzKmIocoT++Oi7wFQ0ppfA3OFLrz3KbF5o7CDoDIonRM3XmXrH8/2ggdNB/oSntUwdG3jYBbdFM29KgIaKrLQP"
    "+QZZacmDshhj3IS40cD+uKPl4JVhswizCFJHI/6pvlx+wR1643jDicnbGvYt5niLC5wL70FB2e4Dy+XOvQfylVrF+iBWO0NUWCxmLOi"
    "/n5gjqMtFgoLcVlAoh0IDL2l2b9OTuVXKskjPA=="
)


def run(ssh, cmd, t=120):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=30)

print("=== tunnel-right.sh head ===")
print(run(ssh, f"head -40 {R}/scripts/tunnel-right.sh 2>/dev/null || echo missing"))

# 补丁：SSH 强制 IPv4
patch_sh = r"""
python3 - <<'PY'
from pathlib import Path
p = Path("/home/bot/55chat-bot/scripts/tunnel-right.sh")
if not p.exists():
    print("no tunnel-right.sh"); raise SystemExit(1)
t = p.read_text(encoding="utf-8")
if " -4 " not in t and "AddressFamily" not in t:
    t = t.replace("ssh -oStrictHostKeyChecking", "ssh -4 -oStrictHostKeyChecking", 1)
    t = t.replace("sshpass -e ssh ", "sshpass -e ssh -4 ", 1)
    p.write_text(t, encoding="utf-8")
    print("patched ssh -4")
else:
    print("already has ipv4")
PY
"""
print(run(ssh, patch_sh))

with ssh.open_sftp() as sftp:
    with sftp.file(f"{R}/secrets/adb_tunnel_key_right", "w") as f:
        f.write(KEY)

print(run(ssh, "pkill -f 'ssh.*60478:localhost' 2>/dev/null; sleep 1; true"))

# 手动 IPv4 隧道测试
manual = f"""
export SSHPASS=$(cat {R}/secrets/adb_tunnel_key_right)
sshpass -e ssh -4 -oStrictHostKeyChecking=accept-new -oServerAliveInterval=30 -oServerAliveCountMax=3 \
  -N -L 60478:localhost:1 -p 1824 s@129.227.134.130 -f 2>&1
sleep 2
adb connect 127.0.0.1:60478
adb devices -l
"""
print("=== manual ssh -4 ===")
print(run(ssh, manual))

print("=== tunnel-right.sh ===")
print(run(ssh, f"bash {R}/scripts/tunnel-right.sh 2>&1 | tail -15"))

if "60478" in run(ssh, "adb devices") and "device" in run(ssh, "adb devices"):
    print("=== restart bot ===")
    print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -15"))
    run(ssh, "sleep 10")
    print(run(ssh, f"cd {R} && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group 127.0.0.1:60478 2>&1 | tail -8"))
    print(run(ssh, f"tail -15 {R}/logs/bot.log | grep -E 'LISTENER|编排|target_group|ERROR|sender' || tail -10 {R}/logs/bot.log"))
else:
    print("FAIL still offline")

ssh.close()
