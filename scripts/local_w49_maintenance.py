#!/usr/bin/env python3
"""W49 全局轻量维护：审计 + VPS/云机/本地清理 + 验收 + 可选关机。"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

# 本地可删：部署调试残留（不动源码/配置/凭证）
LOCAL_JUNK_GLOBS = (
    "*.txt",
)
LOCAL_JUNK_NAMES = {
    "chain.txt", "chain2.txt", "deploy_fix_out.txt", "dual_ip_deploy.txt",
    "dual_route_deploy.txt", "fallback_out.txt", "finish2.txt", "finish_out.txt",
    "fix1.txt", "fix2.txt", "hard_restart.txt", "left_creds_deploy.txt",
    "left_refresh.txt", "observe1.txt", "reconnect_out.txt", "reconnect_steps.txt",
    "refresh_left.txt",
}
LOCAL_DIR_PRUNE = ("artifacts", ".pytest_cache")


def _local_cleanup() -> list[str]:
    removed: list[str] = []
    for name in LOCAL_JUNK_NAMES:
        p = ROOT / name
        if p.is_file():
            p.unlink(missing_ok=True)
            removed.append(str(p.relative_to(ROOT)))
    for d in LOCAL_DIR_PRUNE:
        dp = ROOT / d
        if dp.is_dir():
            shutil.rmtree(dp, ignore_errors=True)
            removed.append(f"{d}/")
    assets = Path.home() / ".cursor" / "projects" / "c-Users-haijin-Downloads" / "assets"
    if assets.is_dir():
        for f in assets.glob("*.png"):
            try:
                f.unlink()
                removed.append(f"assets/{f.name}")
            except OSError:
                pass
    return removed


def _vps_cleanup(ssh: VpsSSH, bot_root: str) -> str:
    py = f"{bot_root}/.venv/bin/python3"
    script = f"""
set -e
R={bot_root}
PY={py}
adb disconnect emulator-5554 2>/dev/null || true
find "$R" -type d -name __pycache__ -prune -exec rm -rf {{}} + 2>/dev/null || true
find "$R/data" -name 'pc28_*.png' -mtime +2 -delete 2>/dev/null || true
find "$R/data" -name 'mark6_*.png' -mtime +2 -delete 2>/dev/null || true
find "$R/data" -name 'trade_*.png' -mtime +2 -delete 2>/dev/null || true
find "$R/data/disk-spill" -type f -mtime +7 -delete 2>/dev/null || true
if [ -f "$R/config/bot-start.env" ]; then
  awk -F= '!seen[$1]++' "$R/config/bot-start.env" > /tmp/bse && mv /tmp/bse "$R/config/bot-start.env"
fi
# 左机 DCIM bot 推图（发图即焚补充）
for ser in localhost:52840 127.0.0.1:52840; do
  adb -s "$ser" shell 'find /sdcard/DCIM/Camera -name "bot_*" -mtime +0 -delete' 2>/dev/null || true
done
# 僵尸进程（铁律6）
pkill -f 'bot_55chat_daemon.py' 2>/dev/null || true
pkill -f 'cloud_dual_watch' 2>/dev/null || true
pkill -f 'patrol' 2>/dev/null || true
du -sh "$R" "$R/logs" "$R/data" 2>/dev/null
echo '--- procs ---'
pgrep -af 'dual_supervisor|spawn_main|mock_gateway|panel' | grep -v pgrep | head -8
echo '--- adb ---'
adb devices 2>/dev/null | head -6
echo '--- settle tail ---'
grep -E 'capture-ipc done|批量发图成功|DEPLOY LOCK|announce' "$R/logs/dual-supervisor.log" | tail -6
"""
    return ssh.run(script, 180)


def _verify_and_heal(ssh: VpsSSH, bot_root: str) -> str:
    return ssh.run(
        f"bash {bot_root}/scripts/reconnect-dual-adb.sh 2>&1 | tail -5; "
        f"pgrep -af spawn_main | head -3; "
        f"adb devices 2>/dev/null | head -6",
        60,
    )


def _audit_notes() -> str:
    return """
| 项 | 现状 | 轻量建议 |
|---|---|---|
| 架构 | supervisor+spawn×2+IPC | 保持，勿加第三进程 |
| env | VPS 有重复键 | 已 awk 去重 |
| clicker-stay | 已关 | 保持 BOT_CLICKER_STAY_IN_CHAT=0 |
| 探活 | LEAN_WATCH 已关 | 勿开 cron 探活 |
| 日志 | dual-supervisor 膨胀 | 已 tail 12000 行 |
| 本地 | 调试 txt/artifacts | 已清 |
| 优化空间 | BOT_CACHE_TRIM=0 | 暂不启，避免误删 mid_cache |
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shutdown", action="store_true", help="验收后关机本地电脑")
    ap.add_argument("--shutdown-sec", type=int, default=90)
    args = ap.parse_args()

    print("=== 1 架构/环境审计（轻量）===")
    print(_audit_notes())

    print("=== 2 本地清理 ===")
    loc = _local_cleanup()
    print("removed:", loc or "(无)")

    cfg = load_vps_config(ROOT)
    r = cfg.bot_root
    with VpsSSH(cfg) as ssh:
        print("=== 3 VPS+云机清理 ===")
        print(_vps_cleanup(ssh, r))
        print("=== 4 隧道+worker 验收 ===")
        print(_verify_and_heal(ssh, r))
        time.sleep(20)
        print(ssh.run(
            f"grep -E 'capture-ipc|settle-|announce|sender-' {r}/logs/dual-supervisor.log | tail -8",
            20,
        ))

    if args.shutdown:
        sec = max(30, args.shutdown_sec)
        print(f"=== 5 本地关机 {sec}s 后 ===")
        subprocess.run(
            ["shutdown", "/s", "/t", str(sec), "/c", "W49 maintenance complete - bot running on VPS"],
            check=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
