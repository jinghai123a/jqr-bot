#!/usr/bin/env python3
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VPS_PASSWORD", "w49-55m-vnc")
from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

cmds = [
    "ls -la /opt/55chat 2>/dev/null || echo 'no /opt/55chat'",
    "du -sh /opt/55chat 2>/dev/null; du -sh /home/bot/.wine55m 2>/dev/null; du -sh /home/bot/.wine68helper 2>/dev/null",
    "ls -la /home/bot/55chat-protocol 2>/dev/null || echo 'no protocol'",
    "ps aux | grep -E 'wine|55-im|68-helper|55chat' | grep -v grep | head -20",
    "systemctl list-units --type=service 2>/dev/null | grep -iE '55|wine|vnc|xvfb' || true",
    "crontab -u bot -l 2>/dev/null | grep -iE '55|wine|68|desktop' || echo 'no bot cron'",
    "ls -la /home/bot/Desktop/ 2>/dev/null",
    "ls -la /home/bot/start*.sh /home/bot/*68* 2>/dev/null",
]

with VpsSSH(load_vps_config(ROOT)) as ssh:
    for c in cmds:
        print("\n===", c[:75], "===\n", ssh.run(c, 40))
