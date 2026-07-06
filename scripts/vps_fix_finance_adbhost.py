#!/usr/bin/env python3
"""对齐 finance.db / device-lock 中 bot adbHost 与 bot-start.env 端口。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH
from bot_ops.vps_ports import dual_adb_ports

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"


def main() -> int:
    rport, lport = dual_adb_ports(ROOT)
    fix_py = f'''
import json
from pathlib import Path
R = Path("{R}")
env = {{}}
for line in (R / "config" / "bot-start.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
lp = env.get("BOT_CLICKER_ADB_PORT", "{lport}")
rp = env.get("BOT_LISTENER_ADB_PORT", "{rport}")
desired = {{"bot-3": f"localhost:{{lp}}", "bot-4": f"localhost:{{rp}}"}}
db = R / "finance.db"
text = db.read_text(encoding="utf-8")
changed = []
for stale in ("localhost:52840", "localhost:50719", "127.0.0.1:52840", "127.0.0.1:50719"):
    if stale in text:
        repl = f"localhost:{{lp}}" if stale.startswith("localhost") else f"127.0.0.1:{{lp}}"
        text = text.replace(stale, repl)
        changed.append(stale)
data = json.loads(text)
def walk(o):
    if isinstance(o, dict):
        bid = str(o.get("id") or "")
        if bid in desired and o.get("adbHost") != desired[bid]:
            o["adbHost"] = desired[bid]
            changed.append(bid)
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)
walk(data)
db.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
print("fixed", changed)
'''
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        ssh.run("cat > /tmp/fix_finance_adb.py << 'PYEOF'\n" + fix_py + "\nPYEOF", 15)
        print(ssh.run(f"{PY} /tmp/fix_finance_adb.py", 20))
        ssh.run(
            f"sed -i 's/localhost:52840/localhost:{lport}/g; "
            f"s/127.0.0.1:52840/127.0.0.1:{lport}/g' "
            f"{R}/config/device-lock.json 2>/dev/null; echo device_lock_ok",
            12,
        )
        print("=== panel bots ===")
        print(
            ssh.run(
                "curl -sf http://127.0.0.1:3000/api/bots 2>/dev/null | python3 -c "
                "\"import sys,json;[print(b.get('id'),b.get('adbHost')) for b in json.load(sys.stdin)]\" "
                "2>/dev/null || echo panel_down",
                15,
            )
        )
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -8", 120))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
