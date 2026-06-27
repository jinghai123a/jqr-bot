#!/usr/bin/env python3
"""VPS 清缓存/旧日志/视觉截图 + 部署坐标修复 + 重启。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)

    def run(cmd: str, t: int = 180) -> str:
        _, o, e = s.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")

    sf = s.open_sftp()
    for rel in (
        "bot_55chat_daemon.py",
        "config/pinned-coords.json",
        "scripts/patch_speed_env.py",
    ):
        p = ROOT / rel
        if p.is_file():
            sf.put(str(p), f"{R}/{rel}")
    sf.close()

    print("=== cleanup ===")
    print(
        run(
            f"""
adb disconnect emulator-5554 2>/dev/null || true
find {R} -type d -name __pycache__ -exec rm -rf {{}} + 2>/dev/null || true
rm -rf {R}/logs/visual-captures {R}/logs/visual-watch.log {R}/logs/visual-cron.log 2>/dev/null || true
rm -f {R}/logs/keepalive-*.log {R}/logs/debug-*.log {R}/logs/autonomous* 2>/dev/null || true
find {R}/scripts -name '_*.py' -size +0c 2>/dev/null | head -5
# 保留 bot.log 最近 5000 行，避免 48MB 拖慢 grep
if [ -f {R}/logs/bot.log ]; then tail -5000 {R}/logs/bot.log > {R}/logs/bot.log.tmp && mv {R}/logs/bot.log.tmp {R}/logs/bot.log; fi
if [ -f {R}/logs/daemon.log ]; then tail -3000 {R}/logs/daemon.log > {R}/logs/daemon.log.tmp && mv {R}/logs/daemon.log.tmp {R}/logs/daemon.log; fi
du -sh {R} {R}/logs /tmp /root/.cache 2>/dev/null
pip3 cache purge 2>/dev/null || true
apt-get clean 2>/dev/null || true
rm -rf /root/.cache/pip/* /tmp/adb* /tmp/*.xml 2>/dev/null || true
journalctl --vacuum-size=80M 2>/dev/null || true
free -h
""",
            120,
        )
    )

    print(run(f"cd {R} && python3 scripts/patch_speed_env.py", 30))
    print(run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -8", 120))
    time.sleep(12)

    ser = "127.0.0.1:60478"
    print("=== try send stuck draft ===")
    print(
        run(
            f"""
adb -s {ser} shell input tap 675 1234
sleep 1
adb -s {ser} shell uiautomator dump /data/local/tmp/clean.xml 2>/dev/null
adb -s {ser} shell cat /data/local/tmp/clean.xml 2>/dev/null | tr '>' '\\n' | grep editTextMessage | head -1
""",
            45,
        )
    )
    print(run("adb devices -l", 20))
    print(run(f"tail -8 {R}/logs/bot.log", 20))
    s.close()
    print("cleanup+deploy done")


if __name__ == "__main__":
    main()
