#!/usr/bin/env python3
"""实时状态快照：双机页面 + 近30min关键log。"""
import paramiko
from datetime import datetime, timezone

H, R = "46.183.27.174", "/home/bot/55chat-bot"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(H, username="root", password="Aa112211@@785*", timeout=30)


def run(cmd: str, t: int = 90) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
print(f"=== 实时快照 {now} ===\n")

print("--- ADB ---")
print(run("adb devices -l | grep -E '52718|60478|List'"))

print("\n--- 视觉（双机当前画面）---")
print(
    run(
        f"W49_VISUAL_LOG={R}/logs/visual-watch.log "
        f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
        f"python3 {R}/scripts/vmos_visual_monitor.py --both --once 2>&1"
    )
)

print("\n--- daemon 进程 ---")
print(run("pgrep -af bot_55chat_daemon | head -1"))

print("\n--- 近30min：公告/封盘/开奖 pipe ---")
print(run(f"grep 'pipe+b64+send' {R}/logs/bot.log | tail -8"))

print("\n--- 近30min：跳过公告/离群 ---")
print(run(f"grep -E '跳过公告|不在群|launcher|webview|我的设置' {R}/logs/bot.log | tail -10"))

print("\n--- 近30min：发图钉死 ---")
print(run(f"grep -E '发图钉死|批量发图成功|UI 发图失败' {R}/logs/bot.log | tail -8"))

print("\n--- 近30min：读指令/回复 ---")
print(run(f"grep -E '公平队列|已回复|pipe\\+b64.*扣|RESOLVE' {R}/logs/bot.log | tail -6"))

print("\n--- 最近一条 listener 页面描述 ---")
print(run(f"grep '右机.*page\\|listener.*群\\|target_group\\|跳过公告' {R}/logs/bot.log | tail -5"))

ssh.close()
