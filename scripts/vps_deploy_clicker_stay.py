#!/usr/bin/env python3
import os
import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
BASE = os.path.dirname(os.path.abspath(__file__))


def run(ssh, cmd, t=90):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=30)
sftp = ssh.open_sftp()
sftp.put(os.path.join(BASE, "..", "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
sftp.close()

# ensure env
patch = f"""
import re
from pathlib import Path
p = Path('{R}/config/bot-start.env')
t = p.read_text(encoding='utf-8')
for k,v in [('BOT_CLICKER_STAY_IN_CHAT','1'),('BOT_CLICKER_STAY_SEC','30')]:
    if re.search('^'+k+'=', t, re.M):
        t = re.sub('^'+k+'=.*', k+'='+v, t, flags=re.M)
    else:
        t += '\\n'+k+'='+v+'\\n'
p.write_text(t, encoding='utf-8')
print('env ok')
"""
print(run(ssh, f"python3 -c {repr(patch)}"))

print(run(ssh, f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -2"))
print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -10"))
print(run(ssh, f"grep -E 'clicker-stay|驻群|DEPLOY LOCK' {R}/logs/bot.log | tail -8"))
ssh.close()
