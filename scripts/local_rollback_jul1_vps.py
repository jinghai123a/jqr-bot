#!/usr/bin/env python3
"""回滚 VPS 至 7月1日 06:48 附近：env + 隧道；daemon 无备份则保持不动。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
ENV_BAK = f"{R}/config/bot-start.env.bak.pre-rollback-1782971630"
SYNC = [
    "bot_tunnel/__init__.py",
    "bot_tunnel/env_io.py",
    "bot_tunnel/expire_schedule.py",
    "bot_tunnel/post_refresh.py",
    "bot_tunnel/refresh.py",
    "bot_tunnel/ssh_parse.py",
    "scripts/reconnect-dual-adb.sh",
    "scripts/vmos-refresh-tunnels.py",
    "scripts/vmos-maintenance-tunnel-cycle.sh",
    "scripts/vmos-maintenance-tunnel-retry.sh",
    "scripts/vps_post_task_tunnel_verify.sh",
    "scripts/tunnel-heal.sh",
    "scripts/tunnel-left.sh",
    "scripts/tunnel-right.sh",
    "scripts/watch-adb-tunnels.sh",
    "scripts/vmos-dual-watchdog.sh",
]

# 7月2日铁律7/会话修复 env（7月1 06:48 前不存在）
STRIP_KEYS = (
    "BOT_LISTENER_ANNOUNCE_TRUST_FALLBACK",
    "BOT_LISTENER_STAY_LOOP",
    "BOT_DAILY_MEM_CYCLE_CRON",
    "BOT_MEM_CYCLE_CLEAN_APP_HOME",
    "BOT_PHYSICAL_OPEN_SNIPPET_P0",
    "BOT_LISTENER_AUTO_RECOVER",
)

RESTORE_ENV = f"""
set -e
cp -a {R}/config/bot-start.env {R}/config/bot-start.env.bak.rollback-$(date +%s) 2>/dev/null || true
cp -a {ENV_BAK} {R}/config/bot-start.env
for k in {' '.join(STRIP_KEYS)}; do
  sed -i "/^$k=/d" {R}/config/bot-start.env
done
grep -E 'ADB_PORT|TRUST|STAY|MEM_CYCLE|ZERO_NAV' {R}/config/bot-start.env | head -20
"""

RESTART = f"""
set +e
bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -15
sleep 10
bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -25
bash {R}/scripts/vps_post_task_tunnel_verify.sh 2>&1 | tail -10
echo '=== PROCS ==='
pgrep -af 'bot_dual_supervisor|spawn_main' | grep -v pgrep | head -6
echo '=== ADB ==='
adb -P 5038 devices -l
adb -P 5039 devices -l
ss -ltnp | grep -E '52840|58433' || true
"""


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        for rel in SYNC:
            lp = ROOT / rel
            if lp.is_file():
                ssh.sftp_put(str(lp), f"{R}/{rel}")
                if rel.endswith(".sh"):
                    ssh.run(f"sed -i 's/\\r$//' {R}/{rel} && chmod +x {R}/{rel}", 8)
        print("=== ENV ===")
        print(ssh.run(RESTORE_ENV, 25))
        print("=== RESTART ===")
        print(ssh.run(RESTART, 180))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
