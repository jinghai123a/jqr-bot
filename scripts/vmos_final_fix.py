#!/usr/bin/env python3
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)

def run(cmd, timeout=600):
    print(">>>", cmd[:90])
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    if out.strip():
        print(out[-4000:])
    if err.strip():
        print("[stderr]", err[:600])
    return out

run("""curl -s -X PATCH http://127.0.0.1:3000/api/bots/bot-3 \
  -H 'Content-Type: application/json' \
  -d '{"adbHost":"127.0.0.1:52840"}'""")
run("sed -i 's/\\r$//' /home/bot/55chat-bot/scripts/setup-cloud-clipboard.sh")
run("sed -i 's/\\r$//' /home/bot/55chat-bot/scripts/vmos-dual-watchdog.sh")
# upload fixed clipboard script from local
def upload_lf(local: str, remote: str) -> None:
    data = open(local, encoding="utf-8").read().replace("\r\n", "\n").encode("utf-8")
    with sftp.file(remote, "wb") as f:
        f.write(data)

sftp = ssh.open_sftp()
upload_lf(r"c:\Users\haijin\Downloads\全自动化机器人\scripts\setup-cloud-clipboard.sh",
            "/home/bot/55chat-bot/scripts/setup-cloud-clipboard.sh")
with sftp.file("/home/bot/55chat-bot/bot_55chat_daemon.py", "wb") as f:
    f.write(open(r"c:\Users\haijin\Downloads\全自动化机器人\bot_55chat_daemon.py", "rb").read())
sftp.close()
run("chmod +x /home/bot/55chat-bot/scripts/setup-cloud-clipboard.sh")
run("bash /home/bot/55chat-bot/scripts/setup-cloud-clipboard.sh", timeout=600)
run("bash /home/bot/55chat-bot/scripts/restart-55chat-bot.sh", timeout=90)
time.sleep(8)
run("cd /home/bot/55chat-bot && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group 127.0.0.1:54936", timeout=120)
run("pgrep -af bot_55chat_daemon; adb devices -l; tail -n 20 /home/bot/55chat-bot/logs/bot.log")
run("tail -n 15 /home/bot/55chat-bot/logs/clipboard-setup.log 2>/dev/null || true")
ssh.close()
