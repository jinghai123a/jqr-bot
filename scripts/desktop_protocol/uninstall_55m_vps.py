#!/usr/bin/env python3
"""Remove 55M desktop protocol stack from VPS (Wine/55-im/68-helper). Keeps 55chat-bot."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

UNINSTALL_SH = r"""#!/bin/bash
set -euo pipefail
export WINEPREFIX=/home/bot/.wine68helper
export WINEARCH=win64

echo "=== 1. stop wine / 68-helper / 55-im ==="
runuser -u bot -- bash -lc '/usr/lib/wine/wineserver -k 2>/dev/null || true'
sleep 2
pkill -u bot -f 'Program Files/68-helper' 2>/dev/null || true
pkill -u bot -f '55-im.exe' 2>/dev/null || true
pkill -u bot -f wineserver 2>/dev/null || true
sleep 2
pgrep -au bot -f wine || echo 'wine stopped'

echo "=== 2. remove desktop protocol dirs ==="
rm -rf /opt/55chat
rm -rf /home/bot/.wine55m
rm -rf /home/bot/.wine68helper
rm -rf /home/bot/55chat-protocol

echo "=== 3. remove launchers / helper scripts ==="
rm -f /home/bot/Desktop/55-im.desktop /home/bot/Desktop/55-im.lnk /home/bot/Desktop/68-helper.desktop
rm -f /home/bot/start68.sh /home/bot/start68cdp.sh /home/bot/start68_prod.sh
rm -f /home/bot/start_inspect.sh /home/bot/restart68_cdp.sh /home/bot/launch68gui.sh
rm -f /home/bot/install68.sh /home/bot/ui68.sh /home/bot/open_settings.sh
rm -f /home/bot/open_helper_ui.sh /home/bot/sigusr1_inspect.sh /home/bot/run_inspect_all.sh
rm -f /home/bot/cdp_*.py /home/bot/kami_probe.js /home/bot/get_mi.js
rm -f /home/bot/68-helper.log /home/bot/68-cdp.log /home/bot/68-main.log
rm -rf /home/bot/kami

echo "=== 4. verify (55chat-bot untouched) ==="
test -d /home/bot/55chat-bot && echo 'OK bot_root exists' || echo 'WARN no 55chat-bot'
ls -la /opt/55chat 2>/dev/null || echo 'OK /opt/55chat gone'
ls -d /home/bot/.wine55m /home/bot/.wine68helper 2>/dev/null || echo 'OK wine prefixes gone'
pgrep -af wine || echo 'OK no wine'
df -h / | tail -1
echo DONE
"""


def main() -> int:
    os.environ.setdefault("VPS_PASSWORD", "w49-55m-vnc")
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        ssh.run(
            "cat > /tmp/uninstall_55m_desktop.sh << 'EOF'\n"
            + UNINSTALL_SH
            + "\nEOF\nchmod +x /tmp/uninstall_55m_desktop.sh",
            20,
        )
        out = ssh.run("bash /tmp/uninstall_55m_desktop.sh", 120)
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
