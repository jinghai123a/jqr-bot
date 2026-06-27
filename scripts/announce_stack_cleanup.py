#!/usr/bin/env python3
"""公告专用栈：关干扰 cron/进程，删 disruptive 脚本，上传 daemon 并重启。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]

UPLOAD = (
    "bot_55chat_daemon.py",
    "scripts/patch_speed_env.py",
)

# VPS 删除（公告无关 / 会 pkill bot、占 ADB、自动 recover）
VPS_RM = (
    "scripts/redeploy-listener-right.sh",
    "scripts/deploy-right-listener-now.sh",
    "scripts/vmos_visual_cron.sh",
    "scripts/vmos_visual_monitor.py",
    "scripts/vmos_visual_watch.py",
    "scripts/autonomous_round_watch.py",
    "scripts/recover_listener_now.py",
    "scripts/full_recovery.py",
    "scripts/close_loop_recovery.py",
    "scripts/resume_closed_loop.py",
    "scripts/fix_until_green.py",
    "scripts/watch_5_rounds.py",
)

CRON_GREP = (
    "vmos_visual_cron",
    "autonomous_round_watch",
    "full_recovery",
    "close_loop_recovery",
    "resume_closed_loop",
    "recover_listener",
    "fix_until_green",
    "watch_5_rounds",
)


def main() -> None:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)

    def run(cmd: str, t: int = 180) -> str:
        _, o, e = s.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")

    sf = s.open_sftp()
    for rel in UPLOAD:
        p = ROOT / rel
        if p.is_file():
            sf.put(str(p), f"{R}/{rel}")
    sf.close()
    print("uploaded", len(UPLOAD), "files")

    kill_pat = "|".join(
        (
            "vmos_visual_monitor",
            "autonomous_round_watch",
            "recover_listener_now",
            "full_recovery",
            "close_loop_recovery",
            "resume_closed_loop",
            "fix_until_green",
            "watch_5_rounds",
        )
    )
    print(run(f"pkill -f '{kill_pat}' 2>/dev/null; true", 30))

    for rel in VPS_RM:
        print(run(f"rm -f {R}/{rel}", 15).strip() or f"rm {rel}")

    grep_v = "|".join(CRON_GREP)
    print(
        run(
            f"(crontab -l 2>/dev/null | grep -Ev '{grep_v}' || true) | crontab -",
            30,
        )
    )
    print("crontab after cleanup:")
    print(run("crontab -l 2>/dev/null || echo '(empty)'", 15))

    print(run(f"cd {R} && python3 scripts/patch_speed_env.py 2>&1", 60))
    print(run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -12", 120))
    time.sleep(18)
    print(run("adb devices 2>&1", 30))
    print(run(f"grep -E 'announce|封盘|sender|STAY_SANITIZE|hide_keyboard' {R}/logs/bot.log 2>&1 | tail -20", 30))
    s.close()
    print("announce_stack_cleanup done")


if __name__ == "__main__":
    main()
