#!/usr/bin/env python3
"""排查 VPS 密钥、隧道、08:56 后发图失败日志。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"


def _mask_env(path_cmd: str) -> str:
    return (
        f"for f in {path_cmd}; do "
        f"if test -f \"$f\"; then echo \"== $f ==\"; "
        f"grep -E '^(VMOS_ACCESS_KEY|VMOS_SECRET_KEY|VMOS_CALLBACK|SSH_PASS|SSH_HOST|LOCAL_PORT)=' \"$f\" "
        f"| sed 's/=.*/=<set>/'; else echo \"MISSING $f\"; fi; done"
    )


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        print("=== secrets on VPS (masked) ===")
        print(
            ssh.run(
                _mask_env(
                    f'"{R}/config/vmos-api.env" "{R}/config/tunnel-left.env" '
                    f'"{R}/config/tunnel-right.env" "{R}/config/vps-ssh.env"'
                ),
                25,
            )
        )
        print("=== deploy scripts present ===")
        print(
            ssh.run(
                f"ls -la {R}/scripts/vps_*.py {R}/bot_ops/deploy_secrets.py 2>/dev/null | tail -20",
                20,
            )
        )
        print("=== sandbox _*.py on VPS (should be absent) ===")
        print(ssh.run(f"ls {R}/scripts/_*.py 2>/dev/null | wc -l", 10))
        print("=== logs since 08:50 today (send/img/errors) ===")
        print(
            ssh.run(
                f"grep -E '2026-07-05 08:5|批量发图|发图异常|左机公告|capture-ipc|队列忙|tunnel|offline|LISTENER 未连接' "
                f"{R}/logs/dual-supervisor.log 2>/dev/null | tail -40",
                30,
            )
        )
        print("=== recent img/send failures ===")
        print(
            ssh.run(
                f"grep -E '发图异常|发送失败|upload|批量发图成功|批量发图失败|grey|retry|open_after' "
                f"{R}/logs/dual-supervisor.log 2>/dev/null | tail -25",
                25,
            )
        )
        print("=== visual now ===")
        py = f"{R}/.venv/bin/python3"
        print(
            ssh.run(
                f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
                f"{py} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1 | grep -E 'state=|model='",
                90,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
