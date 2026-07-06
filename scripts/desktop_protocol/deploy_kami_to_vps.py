#!/usr/bin/env python3
"""Upload 68-helper kami key to VPS and attempt Wine activation."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

LOCAL_CFG = Path(os.environ.get("APPDATA", "")) / "68-helper" / "config.json"
WINE_CFG = (
    "/home/bot/.wine68helper/drive_c/users/bot/AppData/Roaming/68-helper/config.json"
)
WINE_KEY_DIR = "/home/bot/.wine68helper/drive_c/users/bot/Downloads"
REMOTE_KEY = f"{WINE_KEY_DIR}/kami_vps.key"


def main() -> int:
    if not LOCAL_CFG.is_file():
        print("ERR local config missing:", LOCAL_CFG)
        return 1
    cfg = json.loads(LOCAL_CFG.read_text(encoding="utf-8"))
    local_mi = cfg.get("mi", "")
    key_path = Path(cfg.get("kamiFilePath", ""))
    if not key_path.is_file():
        print("ERR kami key missing:", key_path)
        print("local_mi", local_mi)
        return 1

    print("LOCAL_MI", local_mi)
    print("KEY", key_path, key_path.stat().st_size, "bytes")

    vps = load_vps_config(ROOT)
    with VpsSSH(vps) as ssh:
        ssh.run(f"mkdir -p '{WINE_KEY_DIR}' /home/bot/kami", 15)
        ssh.sftp_put(str(key_path), REMOTE_KEY)
        print("uploaded", REMOTE_KEY)

        # collect VPS hardware ids via wine wmic
        env = "export DISPLAY=:0 WINEPREFIX=/home/bot/.wine68helper WINEARCH=win64 WINEDEBUG=-all"
        wmic = (
            f"runuser -u bot -- bash -lc '{env}; "
            "wine cmd /c \"wmic cpu get ProcessorId\"'"
        )
        proc_out = ssh.run(wmic, 30)
        lines = [l.strip() for l in proc_out.replace("\r", "").split("\n") if l.strip()]
        vps_proc = lines[1] if len(lines) > 1 else ""
        print("VPS_ProcessorId", vps_proc)

        # restart helper
        ssh.run(
            "runuser -u bot -- bash -lc '"
            "export WINEPREFIX=/home/bot/.wine68helper; /usr/lib/wine/wineserver -k 2>/dev/null; sleep 2; "
            "cd \"/home/bot/.wine68helper/drive_c/Program Files/68-helper\"; "
            "export DISPLAY=:0 WINEARCH=win64 WINEDEBUG=-all; "
            "nohup wine ./68*.exe >>/home/bot/68-helper.log 2>&1 & sleep 25; "
            "wmctrl -l'",
            60,
        )

        # try copy key into config via wine path (activation still needs UI or IPC)
        win_key = "C:\\\\users\\\\bot\\\\Downloads\\\\kami_vps.key"
        activate_js = f"""
const fs = require('fs');
const path = require('path');
const OUT = 'C:\\\\users\\\\bot\\\\kami_activate.out';
try {{ fs.writeFileSync(OUT, ''); }} catch(e) {{}}
const log = m => fs.appendFileSync(OUT, m + '\\n');
const keyPath = '{win_key}';
const cfgPath = path.join(process.env.APPDATA, '68-helper', 'config.json');
log('key exists ' + fs.existsSync(keyPath));
log('cfg before ' + (fs.existsSync(cfgPath) ? fs.readFileSync(cfgPath,'utf8') : 'MISSING'));
"""
        remote_js = "/home/bot/.wine68helper/drive_c/users/bot/kami_probe.js"
        ssh.run(f"cat > '{remote_js}' << 'JSEOF'\n{activate_js}\nJSEOF", 15)
        ssh.run(
            "runuser -u bot -- bash -lc '"
            "export DISPLAY=:0 WINEPREFIX=/home/bot/.wine68helper WINEARCH=win64 ELECTRON_RUN_AS_NODE=1; "
            "cd \"/home/bot/.wine68helper/drive_c/Program Files/68-helper\"; "
            "wine ./68*.exe \"C:\\\\users\\\\bot\\\\kami_probe.js\"; "
            "cat \"/home/bot/.wine68helper/drive_c/users/bot/kami_activate.out\"'",
            60,
        )

        cfg_out = ssh.run(f"cat '{WINE_CFG}' 2>/dev/null || echo MISSING", 15)
        print("VPS_CONFIG", cfg_out)

    print()
    print("=== IMPORTANT ===")
    print(f"本机设备码 mi={local_mi}")
    print("卡密与设备码绑定；本机密钥在 VPS 上会 KaMi machineId mismatch，除非客服按 VPS 设备码重发。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
