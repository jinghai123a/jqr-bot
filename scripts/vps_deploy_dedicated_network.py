#!/usr/bin/env python3
"""专用网 195.114.193.237：回调路由 + 隧道 + 防断线 watchdog + 重启。"""
from __future__ import annotations

import os
import re
import textwrap
import time

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
DEDICATED = "195.114.193.237"
CALLBACK = f"http://{DEDICATED}:3000/api/vmos/callback"
R = "/home/bot/55chat-bot"
PORTS = {"BOT_LISTENER_ADB_PORT": "60478", "BOT_CLICKER_ADB_PORT": "52718"}
BASE = os.path.dirname(os.path.abspath(__file__))


def run(ssh, cmd, t=180):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


PATCH_CALLBACK = textwrap.dedent(
    r"""
import re
from pathlib import Path
p = Path("/home/bot/55chat-bot/dist/server.cjs")
t = p.read_text(encoding="utf-8")
if "/api/vmos/callback" in t:
    print("callback route exists")
else:
    needle = "async function startServer()"
    ins = r'''
app.post("/api/vmos/callback", (req, res) => {
  try {
    const fs = require("fs");
    const path = require("path");
    const logDir = path.join(process.cwd(), "logs");
    fs.mkdirSync(logDir, { recursive: true });
    const body = req.body || {};
    const line = JSON.stringify({ ts: new Date().toISOString(), ...body }) + "\\n";
    fs.appendFileSync(path.join(logDir, "vmos-callback.log"), line);
    console.log("[vmos-callback]", body.taskBusinessType || "-", body.padCode || "-", body.taskStatus || "-");
    res.json({ code: 200, msg: "success", ts: Date.now() });
  } catch (e) {
    res.status(500).json({ code: 500, msg: e.message || String(e) });
  }
});
'''
    if needle not in t:
        raise SystemExit("startServer anchor missing")
    t = t.replace(needle, ins + needle)
    p.write_text(t, encoding="utf-8")
    print("callback route patched")

# .env APP_URL
envp = Path("/home/bot/55chat-bot/.env")
env = envp.read_text(encoding="utf-8")
new_url = 'APP_URL="http://195.114.193.237:3000"'
if re.search(r'^APP_URL=', env, re.M):
    env = re.sub(r'^APP_URL=.*', new_url, env, flags=re.M)
else:
    env += "\\n" + new_url + "\\n"
envp.write_text(env, encoding="utf-8")
print("APP_URL ok")

# bot-start.env ports
bep = Path("/home/bot/55chat-bot/config/bot-start.env")
bt = bep.read_text(encoding="utf-8")
for k, v in [("BOT_LISTENER_ADB_PORT", "60478"), ("BOT_CLICKER_ADB_PORT", "52718"),
             ("BOT_CLICKER_SEND_IMAGES", "1"), ("BOT_IMG_SEND_MODE", "ui")]:
    if re.search("^" + k + "=", bt, re.M):
        bt = re.sub("^" + k + "=.*", k + "=" + v, bt, flags=re.M)
    else:
        bt += "\\n" + k + "=" + v + "\\n"
bt = re.sub(r"^BOT_SKIP_BOT_IDS=.*\\n", "", bt, flags=re.M)
bep.write_text(bt, encoding="utf-8")
print("bot-start.env ok")

# tunnel env — 勿改 SSH_HOST（专用网 195.114.193.237 仅用于回调，不是云机 SSH 网关）

# vmos-pads local_port
import json
pp = Path("/home/bot/55chat-bot/config/vmos-pads.json")
if pp.exists():
    pads = json.loads(pp.read_text(encoding="utf-8"))
    if pads.get("left"):
        pads["left"]["local_port"] = 52718
    if pads.get("right"):
        pads["right"]["local_port"] = 60478
    pp.write_text(json.dumps(pads, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print("vmos-pads.json ok")

# finance.db adbHost
import json, glob
for db in [Path("/home/bot/55chat-bot/finance.db")]:
    if not db.exists():
        continue
    raw = db.read_text(encoding="utf-8")
    data = json.loads(raw)
    def walk(o):
        if isinstance(o, dict):
            if o.get("id") == "bot-3":
                o["adbHost"] = "127.0.0.1:52718"
            if o.get("id") == "bot-4":
                o["adbHost"] = "127.0.0.1:60478"
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(data)
    db.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("finance.db ok")

# vmos-api.env.example callback note
ex = Path("/home/bot/55chat-bot/config/vmos-api.env.example")
if ex.exists():
    txt = ex.read_text(encoding="utf-8")
    line = "# 回调 URL 在 VMOS 控制台填: http://195.114.193.237:3000/api/vmos/callback"
    if "回调 URL" in txt:
        txt = re.sub(r"# 回调 URL.*", line, txt)
    else:
        txt += "\\n" + line + "\\n"
    ex.write_text(txt, encoding="utf-8")
"""
).strip()


TUNNEL_RIGHT_PATCH = r"""#!/usr/bin/env bash
# listener right — 专用网 + 强制 IPv4
set -euo pipefail
ROOT="/home/bot/55chat-bot"
# shellcheck disable=SC1091
source "${ROOT}/config/tunnel-right.env"
LOCAL_PORT="${LOCAL_PORT:?}"
SSH_HOST="${SSH_HOST:?}"
SSH_PORT="${SSH_PORT:-1824}"
SSH_USER="${SSH_USER:-s}"
SSH_PASS="${SSH_PASS:?}"
ADB_SERIAL="127.0.0.1:${LOCAL_PORT}"

pkill -f "ssh.*${LOCAL_PORT}:localhost:1" 2>/dev/null || true
sleep 1
SSHPASS="${SSH_PASS}" sshpass -e ssh -4 -oStrictHostKeyChecking=accept-new \
  -oServerAliveInterval=30 -oServerAliveCountMax=3 \
  -N -L "${LOCAL_PORT}:localhost:1" -p "${SSH_PORT}" "${SSH_USER}@${SSH_HOST}" -f
sleep 2
adb disconnect "${ADB_SERIAL}" 2>/dev/null || true
adb connect "${ADB_SERIAL}"
adb -s "${ADB_SERIAL}" wait-for-device
echo "OK 右机 ADB @ ${LOCAL_PORT} via ${SSH_HOST}"
"""

TUNNEL_LEFT_PATCH = r"""#!/usr/bin/env bash
# clicker left — 专用网
set -euo pipefail
ROOT="/home/bot/55chat-bot"
# shellcheck disable=SC1091
source "${ROOT}/config/tunnel-left.env"
LOCAL_PORT="${LOCAL_PORT:?}"
SSH_HOST="${SSH_HOST:?}"
SSH_PORT="${SSH_PORT:-1824}"
SSH_USER="${SSH_USER:-s}"
SSH_PASS="${SSH_PASS:?}"
ADB_SERIAL="127.0.0.1:${LOCAL_PORT}"

pkill -f "ssh.*${LOCAL_PORT}:localhost:1" 2>/dev/null || true
sleep 1
SSHPASS="${SSH_PASS}" sshpass -e ssh -oStrictHostKeyChecking=accept-new \
  -oServerAliveInterval=30 -oServerAliveCountMax=3 \
  -N -L "${LOCAL_PORT}:localhost:1" -p "${SSH_PORT}" "${SSH_USER}@${SSH_HOST}" -f
sleep 2
adb disconnect "${ADB_SERIAL}" 2>/dev/null || true
adb connect "${ADB_SERIAL}"
adb -s "${ADB_SERIAL}" wait-for-device
echo "OK 左机 ADB @ ${LOCAL_PORT} via ${SSH_HOST}"
"""


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)
    sftp = ssh.open_sftp()

    # upload patch script
    remote_patch = f"{R}/scripts/_deploy_dedicated_patch.py"
    with sftp.file(remote_patch, "w") as f:
        f.write(PATCH_CALLBACK)
    for name, content in [
        ("tunnel-right.sh", TUNNEL_RIGHT_PATCH),
        ("tunnel-left.sh", TUNNEL_LEFT_PATCH),
    ]:
        path = f"{R}/scripts/{name}"
        with sftp.file(path, "w") as f:
            f.write(content)
        run(ssh, f"chmod +x {path}")
    sftp.close()

    print("=== patch configs ===")
    print(run(ssh, f"python3 {remote_patch}"))

    print("=== test dedicated reachability ===")
    print(run(ssh, f"nc -zv -w 5 {DEDICATED} 1824 2>&1 || true"))

    print("=== refresh VMOS credentials (keep dedicated host) ===")
    print(run(ssh, f"cd {R} && python3 scripts/vmos-refresh-tunnels.py 2>&1 | tail -15"))
    print(run(ssh, f"python3 {remote_patch}"))  # re-apply SSH_HOST after API refresh

    print("=== reconnect tunnels ===")
    print(run(ssh, f"bash {R}/scripts/tunnel-left.sh 2>&1"))
    print(run(ssh, f"bash {R}/scripts/tunnel-right.sh 2>&1"))
    print(run(ssh, "adb devices -l | grep -E '52718|60478'"))

    print("=== cron watchdog ===")
    cron_py = f"""
import subprocess
cur = subprocess.run(['crontab','-l'], capture_output=True, text=True)
existing = cur.stdout if cur.returncode==0 else ''
lines = [ln for ln in existing.splitlines() if ln.strip() and 'vmos-dual-watchdog' not in ln and 'watch-adb-tunnels' not in ln]
lines += [
 '*/2 * * * * /home/bot/55chat-bot/scripts/vmos-dual-watchdog.sh',
 '*/15 * * * * /home/bot/55chat-bot/scripts/watch-adb-tunnels.sh',
]
subprocess.run(['crontab','-'], input='\\n'.join(lines)+'\\n', text=True, check=True)
print('crontab ok')
"""
    with ssh.open_sftp().file(f"{R}/scripts/_cron_watchdog.py", "w") as f:
        f.write(cron_py)
    print(run(ssh, f"python3 {R}/scripts/_cron_watchdog.py"))

    print("=== restart panel ===")
    run(ssh, "pkill -f 'node dist/server' || true")
    time.sleep(2)
    run(ssh, f"cd {R} && nohup node dist/server.cjs >> logs/server.log 2>&1 &")
    time.sleep(4)
    print(run(ssh, f"curl -s -o /dev/null -w '%{{http_code}}' -X POST {CALLBACK} -H 'Content-Type: application/json' -d '{{\"taskBusinessType\":999,\"padCode\":\"test\",\"taskStatus\":3}}'"))
    print(run(ssh, f"tail -2 {R}/logs/vmos-callback.log 2>/dev/null"))

    print("=== restart bot ===")
    print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -15"))
    time.sleep(15)
    print(run(ssh, f"tail -40 {R}/logs/bot.log | grep -E 'DEPLOY|LISTENER|CLICKER|编排|ERROR|target_group' | tail -20"))
    ssh.close()


if __name__ == "__main__":
    main()
