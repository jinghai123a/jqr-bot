#!/usr/bin/env python3
"""上传核心 daemon、对齐 env、停掉无用监控、重启双脑。"""
import os
import time
import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
BASE = os.path.dirname(os.path.abspath(__file__))


def run(ssh, cmd, t=180):
    chan = ssh.get_transport().open_session()
    chan.settimeout(t)
    chan.exec_command(cmd)
    buf = b""
    deadline = time.time() + t
    while time.time() < deadline:
        if chan.recv_ready():
            buf += chan.recv(8192)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(8192)
            break
        time.sleep(0.15)
    return buf.decode("utf-8", "replace")


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=30)
print("=== upload ===")
run(ssh, f"mkdir -p {R}/docs", 10)
sftp = ssh.open_sftp()
sftp.put(os.path.join(BASE, "..", "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
sftp.put(os.path.join(BASE, "patch_speed_env.py"), f"{R}/scripts/patch_speed_env.py")
sftp.put(os.path.join(BASE, "verify_dual_brain.py"), f"{R}/scripts/verify_dual_brain.py")
sftp.put(os.path.join(BASE, "live_cloud_verify.py"), f"{R}/scripts/live_cloud_verify.py")
sftp.put(os.path.join(BASE, "purge_unused_apps.py"), f"{R}/scripts/purge_unused_apps.py")
for doc in ("固定-公告顺序与内容文本.md", "固定-全局线程与资源分发.md"):
    lp = os.path.join(BASE, "..", "docs", doc)
    if os.path.isfile(lp):
        sftp.put(lp, f"{R}/docs/{doc}")
pinned = os.path.join(BASE, "..", "config", "pinned-coords.json")
if os.path.isfile(pinned):
    sftp.put(pinned, f"{R}/config/pinned-coords.json")
sftp.close()

print("=== stop monitors ===")
print(run(ssh, "pkill -f dual-auto-heal.py; pkill -f dual-monitor-1h.py; pkill -f poll_dual_monitor; true", 15))
print(run(ssh, f"rm -f {R}/scripts/dual-auto-heal.py {R}/scripts/dual-monitor-1h.py", 10))

print("=== patch env ===")
print(run(ssh, f"python3 {R}/scripts/patch_speed_env.py", 20))

print("=== cloud-phone allowlist (55M + ADB Keyboard only) ===")
print(run(ssh, f"python3 {R}/scripts/purge_unused_apps.py 2>&1 | tail -20", 180))

print("=== panel api ===")
print(run(ssh, f"""
if curl -sf http://127.0.0.1:3000/api/bots >/dev/null; then
  echo "panel api ok"
else
  echo "starting panel api"
  cd {R} && nohup npm run start > logs/panel.log 2>&1 &
  sleep 6
  curl -sf http://127.0.0.1:3000/api/bots >/dev/null && echo "panel api started" || (echo "panel api still down"; tail -30 {R}/logs/panel.log)
fi
""", 45))

print("=== tunnels + restart ===")
print(run(ssh, f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -1; bash {R}/scripts/tunnel-right.sh 2>&1 | tail -1", 90))
print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -14", 120))
time.sleep(10)

print("=== quick check ===")
print(run(ssh, f"""
grep -E 'ADB_PORT|SKIP|IMG_SEND|LISTENER_SEND|CLICKER_OPTIONAL' {R}/config/bot-start.env
pgrep -af 'bot_55chat_daemon|dual-auto' || true
LP=$(grep '^BOT_LISTENER_ADB_PORT=' {R}/config/bot-start.env | cut -d= -f2)
CP=$(grep '^BOT_CLICKER_ADB_PORT=' {R}/config/bot-start.env | cut -d= -f2)
adb devices -l | grep -E "$LP|$CP"
tail -12 {R}/logs/bot.log
""", 30))

print("=== verify (硬性验收) ===")
rc_out = run(ssh, f"python3 {R}/scripts/verify_dual_brain.py; echo EXIT:$?", 90)
print(rc_out)
if "EXIT:0" not in rc_out:
    raise SystemExit("verify_dual_brain 未通过，部署中止汇报")

ssh.close()
print("done")
