#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

OLD, NEW = "46.183.27.174", "195.114.193.136"
R = "/home/bot/55chat-bot"


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        before = ssh.run(f"grep -R '{OLD}' {R}/config 2>/dev/null | head -20", 20)
        print("BEFORE", before or "(none)")
        ssh.run(
            f"for f in $(find {R}/config -type f \\( -name '*.env' -o -name '*.json' \\)); do "
            f"sed -i 's/{OLD}/{NEW}/g' \"$f\"; done; echo sed_ok",
            30,
        )
        after = ssh.run(f"grep -R '{OLD}' {R}/config 2>/dev/null | head -5", 20)
        print("AFTER", after or "VPS_CONFIG_CLEAN")
        print("CALLBACK", ssh.run(f"grep VMOS_CALLBACK {R}/config/vmos-api.env", 10))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
