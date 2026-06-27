#!/usr/bin/env python3
import os
import time
import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
BASE = os.path.dirname(os.path.abspath(__file__))


def run(ssh, cmd, t=90):
    chan = ssh.get_transport().open_session()
    chan.settimeout(t)
    chan.exec_command(cmd)
    buf = b""
    deadline = time.time() + t
    while time.time() < deadline:
        if chan.recv_ready():
            buf += chan.recv(4096)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(4096)
            break
        time.sleep(0.2)
    return buf.decode("utf-8", "replace")


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=30)
sftp = ssh.open_sftp()
sftp.put(os.path.join(BASE, "_restore_ssh_hosts.py"), f"{R}/scripts/_restore_ssh_hosts.py")
sftp.close()

print(run(ssh, f"python3 {R}/scripts/_restore_ssh_hosts.py", 20))
print("=== left tunnel ===")
print(run(ssh, f"bash {R}/scripts/tunnel-left.sh 2>&1", 45))
print("=== right tunnel ===")
print(run(ssh, f"bash {R}/scripts/tunnel-right.sh 2>&1", 45))
print(run(ssh, "adb devices -l", 20))
print(run(ssh, f"curl -s -m 5 -X POST http://127.0.0.1:3000/api/vmos/callback -H 'Content-Type: application/json' -d '{{\"taskBusinessType\":999}}'", 10))
print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -6", 60))
ssh.close()
