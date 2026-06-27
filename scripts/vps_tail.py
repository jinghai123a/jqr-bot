#!/usr/bin/env python3
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)
_, o, _ = ssh.exec_command("tail -n 100 /home/bot/55chat-bot/logs/bot.log", timeout=30)
print(o.read().decode("utf-8", errors="replace"))
ssh.close()
