#!/usr/bin/env python3
"""
瘦 VPS 栈部署 — VPS 24h 自治，本地仅排查。

安装（仅业务功能白名单）：
  · dual_supervisor + spawn×2 + Panel + mock_gateway + 隧道脚本
  · cron：lean-boot @reboot、19:00 隧道刷新、19:35 铁律7、kill-legacy
禁止：vmos-dual-watchdog、*/5 lean-watch、patrol/SRE、local_* / tests / docs 上传
"""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

SYNC_FILES = [
    "bot_55chat_daemon.py",
    "bot_dual_supervisor.py",
    "mock_gateway.py",
    "board_capture.py",
    "bot_ops/runtime.py",
    "bot_ops/config.py",
    "bot_ops/adb_isolated.py",
    "bot_ops/process_hygiene.py",
    "bot_ops/port_cleanup.py",
    "bot_ops/clicker_busy_ipc.py",
    "bot_ops/cloud_memory_clean.py",
    "bot_ops/cmd_claim_ipc.py",
    "bot_ops/screen_vision.py",
    "bot_ops/app_purge.py",
    "bot_ops/ssh_client.py",
    "bot_ops/api_timing.py",
    "bot_ops/time_sync.py",
    "bot_ops/ephemeral_burn.py",
    "bot_ops/daily_memory_cycle.py",
    "bot_ops/vmos_presets.py",
    "bot_tunnel/refresh.py",
    "bot_tunnel/env_io.py",
    "bot_tunnel/lock.py",
    "scripts/restart-55chat-bot.sh",
    "scripts/reconnect-dual-adb.sh",
    "scripts/lean-boot.sh",
    "scripts/ensure_bots_active.py",
    "scripts/vmos-refresh-tunnels.py",
    "scripts/tunnel-left.sh",
    "scripts/tunnel-right.sh",
    "scripts/tunnel-connect-official.sh",
    "scripts/vps_post_task_tunnel_verify.sh",
    "scripts/vps_minimal_cron.sh",
    "scripts/kill-legacy-if-dual.sh",
    "scripts/daily_memory_cycle.py",
    "scripts/cloud_memory_maintain.py",
    "scripts/_panel_keepalive.sh",
    "scripts/vmos_api/__init__.py",
    "scripts/vmos_api/client.py",
    "scripts/vmos_api/errors.py",
    "scripts/vmos_api/signer.py",
    "scripts/vmos_api/transport.py",
    "scripts/vmos_api_client.py",
    "config/vmos-pads.json",
    "config/pinned-coords.json",
]

ENV_LINES = [
    "BOT_DUAL_PROCESS=1",
    "BOT_ADB_ISOLATED=1",
    "BOT_LISTENER_ADB_SERVER_PORT=5038",
    "BOT_CLICKER_ADB_SERVER_PORT=5039",
    "BOT_LISTENER_ADB_PORT=58433",
    "BOT_CLICKER_ADB_PORT=52840",
    "BOT_LISTENER_ID=bot-4",
    "BOT_CLICKER_IDS=bot-3",
    "BOT_LISTENER_ZERO_NAV=1",
    "BOT_CLICKER_ZERO_NAV=1",
    "BOT_CLICKER_STAY_IN_CHAT=0",
    "BOT_LISTENER_OUTBOUND_POOL_MAX=10",
    "BOT_CLICKER_OUTBOUND_POOL_MAX=3",
    "BOT_CLICKER_CONTEXT_REFRESH_SEC=10",
    "BOT_PANEL_HTTP_TIMEOUT_SEC=3",
    "BOT_CAPTURE_BURN_AFTER_SEND=1",
    "BOT_GALLERY_PURGE_SEC=3600",
    "BOT_DISK_SPILL_RETENTION_DAYS=7",
    "BOT_LISTENER_TUNNEL_BIND=195.114.193.237",
    "BOT_CLICKER_TUNNEL_BIND=195.114.193.136",
    "BOT_LISTENER_ANNOUNCE_TRUST_FALLBACK=0",
]

def _purge_probe_storms(ssh, r: str) -> str:
    """铁律1：杀隧道探活/左机 stay 看门狗，禁止抢线程。"""
    return ssh.run(
        f"pkill -9 -f vmos-dual-watchdog.sh 2>/dev/null; "
        f"pkill -9 -f watch-adb-tunnels.sh 2>/dev/null; "
        f"pkill -9 -f vps_lean_watchdog.py 2>/dev/null; "
        f"systemctl stop 55chat-patrol.service 2>/dev/null; "
        f"systemctl disable 55chat-patrol.service 2>/dev/null; "
        f"systemctl mask 55chat-patrol.service 2>/dev/null; "
        f"pkill -9 -f sre_24h_watchdog.py 2>/dev/null; "
        f"pkill -9 -f live_cloud_patrol.py 2>/dev/null; "
        f"pkill -9 -f cloud_dual_watch.py 2>/dev/null; "
        f"pkill -9 -f w49_l3_watchdog.py 2>/dev/null; "
        f"cd {r} && {r}/.venv/bin/python3 -c "
        f"\"from bot_ops.process_hygiene import disable_patrol_systemd, purge_legacy_patrol; "
        f"disable_patrol_systemd(); purge_legacy_patrol()\" 2>/dev/null; "
        f"echo purged",
        40,
    )


def _sync_bundle(cfg, bot_root: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tf:
        tar_path = tf.name
    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            for rel in SYNC_FILES:
                lp = ROOT / rel.replace("/", os.sep)
                if lp.is_file():
                    tar.add(lp, arcname=rel.replace("\\", "/"))
        remote = f"/tmp/55chat-lean-{int(time.time())}.tar.gz"
        with VpsSSH(cfg) as ssh:
            ssh.sftp_put(tar_path, remote)
            print(
                ssh.run(
                    f"mkdir -p {bot_root} && cd {bot_root} && tar xzf {remote} && rm -f {remote} && "
                    f"find {bot_root}/scripts -name '*.sh' -exec sed -i 's/\\r$//' {{}} +",
                    120,
                )
            )
    finally:
        try:
            os.unlink(tar_path)
        except OSError:
            pass


def main() -> int:
    cfg = load_vps_config(ROOT, prompt_password=False)
    r = cfg.bot_root
    py = f"{r}/.venv/bin/python3"

    print("=== [1/7] 同步瘦栈代码（白名单，无 local_* / tests / docs）===")
    _sync_bundle(cfg, r)

    with VpsSSH(cfg) as ssh:
        print("=== [2/7] bot-start.env（铁律5 env + 52840 左端口）===")
        for line in ENV_LINES:
            key = line.split("=", 1)[0]
            ssh.run(
                f"touch {r}/config/bot-start.env; "
                f"grep -q '^{key}=' {r}/config/bot-start.env && "
                f"sed -i 's|^{key}=.*|{line}|' {r}/config/bot-start.env || "
                f"echo '{line}' >> {r}/config/bot-start.env",
                10,
            )

        print("=== [3/7] 杀探活风暴 / patrol / legacy SRE ===")
        print(_purge_probe_storms(ssh, r))

        print("=== [4/7] 生产 cron（vps_minimal_cron：无 watchdog 探活）===")
        print(
            ssh.run(
                f"chmod +x {r}/scripts/vps_minimal_cron.sh {r}/scripts/kill-legacy-if-dual.sh && "
                f"sed -i 's/\\r$//' {r}/scripts/vps_minimal_cron.sh {r}/scripts/kill-legacy-if-dual.sh && "
                f"bash {r}/scripts/vps_minimal_cron.sh 2>&1",
                25,
            )
        )

        print("=== [5/7] VMOS OpenAPI 隧道刷新（一次性，非 cron 探活）===")
        print(ssh.run(f"cd {r} && timeout 180 {py} scripts/vmos-refresh-tunnels.py --reconnect 2>&1 | tail -25", 200))

        print("=== [6/7] lean-boot 拉起双栈 ===")
        print(ssh.run(f"bash {r}/scripts/lean-boot.sh 2>&1 | tail -25", 200))

        print("=== [7/7] 铁律1 隧道验收（一次性 verify，非周期探活）===")
        verify = f"""
uptime
pgrep -af 'vmos-dual-watchdog|vps_lean_watchdog|watch-adb-tunnels' || echo NO_PROBE_STORM
pgrep -af 'dual_supervisor|mock_gateway' | grep -v bash | head -6
ss -ltnp | grep -E ':3000|:8765|:8770|:5038|:5039' || true
adb -P 5038 devices -l | grep 58433 || true
adb -P 5039 devices -l | grep 52840 || true
bash {r}/scripts/vps_post_task_tunnel_verify.sh 2>&1 | tail -5
crontab -l
curl -s -m 3 -o /dev/null -w 'panel=%{{http_code}}\\n' http://127.0.0.1:3000/api/bots
"""
        print(ssh.run(verify, 120))

    print("\n[LEAN_VPS_DEPLOY] DONE — 排查: python scripts/local_iron_laws_verify.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
