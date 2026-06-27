#!/usr/bin/env python3
import paramiko, time
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)
R = "/home/bot/55chat-bot"
_, o, _ = ssh.exec_command(
    f"sed -i 's/^BOT_LISTENER_SEND_MODE=.*/BOT_LISTENER_SEND_MODE=auto/' {R}/config/bot-start.env && "
    f"grep BOT_LISTENER_SEND_MODE {R}/config/bot-start.env"
)
print(o.read().decode())
_, o, _ = ssh.exec_command(f"bash {R}/scripts/restart-55chat-bot.sh", timeout=60)
print(o.read().decode())
time.sleep(5)
_, o, _ = ssh.exec_command(
    f"cd {R} && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group 127.0.0.1:54936",
    timeout=90,
)
print(o.read().decode())
ssh.close()
