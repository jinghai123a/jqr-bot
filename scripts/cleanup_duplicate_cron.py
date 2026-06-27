#!/usr/bin/env python3
"""清理 VPS 重复 cron：只保留 cloud_dual_watch + watch-log-stall + 6h 隧道刷新。"""
from __future__ import annotations

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"

# 保留项（其余 root crontab / cron.d 里的巡检类任务一律去掉）
KEEP_ROOT = [
    (
        "0 */6 * * * cd /home/bot/55chat-bot && "
        "python3 scripts/vmos-refresh-tunnels.py --reconnect "
        ">> logs/vmos-refresh.log 2>&1"
    ),
    (
        "*/5 * * * * flock -n /tmp/cloud_dual_watch.lock "
        f"python3 {R}/scripts/cloud_dual_watch.py "
        f">> {R}/logs/cloud-watch-cron.log 2>&1"
    ),
]

CRON_D = f"""# 55chat-bot — 仅日志卡死检测（ADB/在群/daemon 由 cloud_dual_watch 负责）
*/5 * * * * root bash {R}/scripts/watch-log-stall.sh >> {R}/logs/watchdog.log 2>&1
"""


def run(ssh: paramiko.SSHClient, cmd: str, t: int = 90) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)

    cur = run(ssh, "crontab -l 2>/dev/null || true", 15)
    drop_keys = (
        "vmos-dual-watchdog",
        "watch-adb-tunnels",
        "cloud_dual_watch",
        "vmos-refresh-tunnels",
        "watch-log-stall",
    )
    kept_other = [
        ln
        for ln in cur.splitlines()
        if ln.strip() and not any(k in ln for k in drop_keys)
    ]
    new_root = kept_other + KEEP_ROOT
    payload = "\n".join(new_root) + "\n"
    run(ssh, f"crontab - <<'EOF'\n{payload}EOF", 15)

    run(ssh, f"cat > /etc/cron.d/55chat-bot <<'EOF'\n{CRON_D}EOF", 15)

    print("=== root crontab (55chat related) ===")
    print(run(ssh, "crontab -l | grep -E '55chat|cloud_dual|vmos-refresh|watchdog|watch-adb|watch-log' || true", 15))
    print("=== /etc/cron.d/55chat-bot ===")
    print(run(ssh, "cat /etc/cron.d/55chat-bot", 15))
    ssh.close()
    print("done — removed: vmos-dual-watchdog */2, watch-adb-tunnels */15 (dup), cron.d dup refresh")


if __name__ == "__main__":
    main()
