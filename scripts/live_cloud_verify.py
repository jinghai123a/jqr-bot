#!/usr/bin/env python3
"""云机实况验收：ADB 读屏 + 截图 + 发送环回，不只盯日志。"""
from __future__ import annotations

import base64
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
RIGHT = "127.0.0.1:60478"
LEFT = "localhost:56121"
ART = Path(__file__).resolve().parents[1] / "artifacts" / "live-verify"

CHECKS: list[tuple[str, bool, str]] = []


def ok(name: str, passed: bool, detail: str) -> None:
    CHECKS.append((name, passed, detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def run(ssh: paramiko.SSHClient, cmd: str, t: int = 90) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def adb(ssh: paramiko.SSHClient, serial: str, shell_cmd: str, t: int = 45) -> str:
    return run(ssh, f"adb -s {serial} {shell_cmd}", t)


def pull_png(ssh: paramiko.SSHClient, serial: str, label: str) -> Path | None:
    ART.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    remote = f"/tmp/afu_{label}_{ts}.png"
    local = ART / f"{label}_{ts}.png"
    run(ssh, f"adb -s {serial} exec-out screencap -p > {remote} 2>/dev/null", 35)
    try:
        sf = ssh.open_sftp()
        sf.get(remote, str(local))
        sf.close()
        run(ssh, f"rm -f {remote}", 10)
        return local if local.is_file() and local.stat().st_size > 800 else None
    except Exception as ex:
        ok(f"截图 {label}", False, str(ex))
        return None


def focus_activity(ssh: paramiko.SSHClient, serial: str) -> str:
    out = adb(ssh, serial, 'shell "dumpsys window displays 2>/dev/null | grep mCurrentFocus | head -1"', 20)
    m = re.search(r"(\S+/[\w.]+)\}", out)
    return m.group(1) if m else out.strip()[:120]


def draft_text(ssh: paramiko.SSHClient, serial: str) -> str:
    adb(ssh, serial, "shell uiautomator dump /data/local/tmp/v.xml 2>/dev/null", 35)
    xml = adb(ssh, serial, "shell cat /data/local/tmp/v.xml 2>/dev/null", 15)
    m = re.search(r'editTextMessage[^>]*text="([^"]*)"', xml)
    if m:
        return m.group(1)
    m2 = re.search(r"editTextMessage", xml)
    return "(空)" if m2 else "无输入框"


def right_send_probe(ssh: paramiko.SSHClient) -> None:
    """右机：b64 灌字 → tap 发送 → 验 draft 清空。"""
    test = f"阿福实况验收{int(time.time()) % 10000}"
    b64 = base64.b64encode(test.encode("utf-8")).decode("ascii")
    run(
        ssh,
        f'adb -s {RIGHT} shell am broadcast -a ADB_INPUT_B64 --es msg "{b64}"',
        15,
    )
    time.sleep(0.4)
    before = draft_text(ssh, RIGHT)
    adb(ssh, RIGHT, "shell input tap 674 1234", 10)
    time.sleep(0.8)
    after = draft_text(ssh, RIGHT)
    cleared = after in ("", "(空)", "输入消息") or test not in after
    ok(
        "右机 b64+tap 发送环回",
        cleared,
        f"before={before[:24]!r} after={after[:24]!r}",
    )


def left_attach_probe(ssh: paramiko.SSHClient) -> None:
    """左机：附件栏已开则直接点图片；否则点 + 展开。"""
    act = focus_activity(ssh, LEFT)
    if "GroupChatActivity" not in act:
        ok("左机在群聊", False, act)
        return
    ok("左机在群聊", True, act.split("/")[-1])

    run(ssh, f"adb -s {LEFT} shell cmd input_method hide", 10)
    run(ssh, f"adb -s {LEFT} shell input keyevent 111", 8)
    time.sleep(0.35)

    def dump_xml() -> str:
        run(ssh, f"adb -s {LEFT} shell uiautomator dump /data/local/tmp/v.xml 2>/dev/null", 50)
        time.sleep(0.2)
        return run(ssh, f"adb -s {LEFT} shell cat /data/local/tmp/v.xml 2>/dev/null", 20)

    xml = dump_xml()
    iv = xml.count("ImageView")
    menu_open = (
        "图片" in xml
        or ("拍摄" in xml and "红包" in xml)
        or iv >= 6
    )
    if menu_open:
        ok("左机附件栏", True, "已展开(无需再点+)")
    else:
        run(ssh, f"adb -s {LEFT} shell input tap 45 1234", 12)
        time.sleep(0.8)
        xml = dump_xml()
        iv = xml.count("ImageView")
        menu_open = "图片" in xml or iv >= 6
        ok("左机 + 展开附件栏", menu_open, f"ImageView={iv}" if menu_open else xml[:80])

    if menu_open:
        run(ssh, f"adb -s {LEFT} shell input tap 90 787", 12)
        time.sleep(1.0)
        xml2 = dump_xml()
        iv2 = xml2.count("ImageView")
        gallery = "/9" in xml2.replace(" ", "") or "相册" in xml2 or "最近" in xml2 or iv2 >= 15
        ok("左机 点图片进相册", gallery, f"ImageView={iv2}" if gallery else xml2[:100])
        run(ssh, f"adb -s {LEFT} shell input keyevent 111", 8)
        run(ssh, f"adb -s {LEFT} shell input tap 34 86", 8)


def daemon_threads(ssh: paramiko.SSHClient) -> None:
    raw = run(ssh, f"tail -500 {R}/logs/bot.log")
    procs = run(ssh, "pgrep -af 'bot_55chat|ui-collect|fire' || true")
    checks = [
        ("ui-collect", "ui-collect" in raw or "ui-collect" in procs),
        ("listener-fire", "fire 线程点发送" in raw or "fire-thread" in raw),
        ("clicker-fire", "左机 fire" in raw or "clicker-fire" in procs),
        ("sender-bot-4", "sender-bot-4" in raw),
        ("clicker-img-bot-3", "clicker-img-bot-3" in raw),
    ]
    for name, hit in checks:
        ok(f"线程 {name}", hit, "已启动" if hit else "未见")


def main() -> int:
    print(f"=== 云机实况验收 UTC {datetime.now(timezone.utc).isoformat()} ===\n")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, username="root", password=PW, timeout=30)
    except Exception as ex:
        ok("VPS SSH", False, str(ex))
        return 1

    adb_out = run(ssh, "adb devices -l")
    ok("右机 ADB online", RIGHT in adb_out and "device" in adb_out, RIGHT)
    ok("左机 ADB online", LEFT in adb_out and "device" in adb_out, LEFT)

    r_act = focus_activity(ssh, RIGHT)
    ok("右机在群聊", "GroupChatActivity" in r_act, r_act)

    r_png = pull_png(ssh, RIGHT, "right")
    ok("右机截图", r_png is not None, str(r_png) if r_png else "失败")

    l_png = pull_png(ssh, LEFT, "left")
    ok("左机截图", l_png is not None, str(l_png) if l_png else "失败")

    right_send_probe(ssh)
    left_attach_probe(ssh)
    daemon_threads(ssh)

    ssh.close()

    fails = [c for c in CHECKS if not c[1]]
    print(f"\n=== 结果 {len(CHECKS) - len(fails)}/{len(CHECKS)} PASS ===")
    if fails:
        for name, _, detail in fails:
            print(f"  FAIL {name}: {detail}")
        return 1
    print("云机实况全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
