#!/usr/bin/env python3
"""盯盘：连续 5 期「开局公告 pipe + 左机批量发图」均成功才 exit 0。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
LOG = f"{R}/logs/bot.log"
ROOT = Path(__file__).resolve().parents[1]
NEED_STREAK = 5
POLL_SEC = 20
MAX_HOURS = 6


def connect() -> paramiko.SSHClient:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)
    return s


def run(ssh: paramiko.SSHClient, cmd: str, t: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def upload_core(ssh: paramiko.SSHClient) -> None:
    sf = ssh.open_sftp()
    for rel in (
        "bot_55chat_daemon.py",
        "scripts/recover_listener_now.py",
        "scripts/vmos_visual_monitor.py",
        "scripts/confirm_e2e.py",
        "scripts/fix_until_green.py",
    ):
        p = ROOT / rel
        if p.is_file():
            sf.put(str(p), f"{R}/{rel}")
    sf.close()


def listener_ok(ssh: paramiko.SSHClient) -> bool:
    out = run(
        ssh,
        f"""python3 - <<'PY'
import os, sys
sys.path.insert(0, "{R}")
os.chdir("{R}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="127.0.0.1:60478"
bot={{"id":"bot-4","associatedGroup":"苍井空测试"}}
root=d.ui_hierarchy(serial)
print("OK" if d.listener_in_group_for_send(root, bot, serial) and d.is_group_chat_activity(serial) else "NO")
PY""",
        60,
    )
    return "OK" in out


def visual_bad(ssh: paramiko.SSHClient) -> list[str]:
    out = run(
        ssh,
        f"python3 {R}/scripts/vmos_visual_monitor.py --both --once 2>&1",
        45,
    )
    bad = []
    for line in out.splitlines():
        m = re.search(r"(clicker|listener)\s+\S+\s+state=(\w+)", line)
        if not m:
            continue
        role, st = m.group(1), m.group(2)
        if st in ("launcher", "webview", "offline", "other"):
            bad.append(f"{role}={st}")
        elif st != "target_group":
            bad.append(f"{role}={st}")
    return bad


def recover(ssh: paramiko.SSHClient) -> None:
    run(ssh, f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 120)


def parse_log_events(text: str) -> tuple[set[int], set[int], list[str]]:
    """返回 (开局公告 rid 集合, 发图成功 rid 集合, 最近问题行)。"""
    open_rids: set[int] = set()
    img_rids: set[int] = set()
    issues: list[str] = []
    pending_settle_rid: int | None = None

    open_pipe = re.compile(r"pipe\+b64\+send.*?:\s*(.+)$")
    open_adb = re.compile(r"开局公告 rid=(\d+)|\[ADB\] 开局公告 rid=(\d+)")
    settle = re.compile(r"结算 rid=(\d+)")
    img_ok = re.compile(r"批量发图成功|\[ADB\] 批量发图成功")
    img_fail = re.compile(r"批量发图失败|UI 发图失败|左机 UI 发图失败")
    skip = re.compile(r"跳过公告|不在群聊")

    for ln in text.splitlines():
        m = settle.search(ln)
        if m:
            pending_settle_rid = int(m.group(1))
        m = open_adb.search(ln)
        if m:
            rid_s = m.group(1) or m.group(2)
            if rid_s:
                open_rids.add(int(rid_s))
        mp = open_pipe.search(ln)
        if mp:
            body = mp.group(1)
            rm = re.search(r"(\d{6,})期", body)
            if rm and ("新一" in body or "局开" in body or "【" in ln):
                open_rids.add(int(rm.group(1)))
        if img_ok.search(ln):
            if pending_settle_rid is not None:
                img_rids.add(pending_settle_rid)
        ms = re.search(r"结算 rid=(\d+) 截图(\d+)张", ln)
        if ms:
            img_rids.add(int(ms.group(1)))
        if img_fail.search(ln):
            issues.append(ln[-160:])
        if skip.search(ln):
            issues.append(ln[-160:])

    return open_rids, img_rids, issues


def streak_ok(open_rids: set[int], img_rids: set[int]) -> tuple[int, list[int]]:
    """同一期 rid 既有开局公告又有结算发图，连续 5 期。"""
    complete = sorted(r for r in open_rids if r in img_rids)
    if not complete:
        return 0, []
    best = 1
    best_seq = [complete[0]]
    cur = 1
    cur_seq = [complete[0]]
    for i in range(1, len(complete)):
        if complete[i] == complete[i - 1] + 1:
            cur += 1
            cur_seq.append(complete[i])
        else:
            cur = 1
            cur_seq = [complete[i]]
        if cur > best:
            best = cur
            best_seq = list(cur_seq)
    return best, best_seq


def fix_if_broken(ssh: paramiko.SSHClient) -> None:
    if listener_ok(ssh):
        bad = visual_bad(ssh)
        if not bad:
            return
    recover(ssh)
    time.sleep(6)
    if not listener_ok(ssh):
        run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -2", 120)
        time.sleep(18)
        recover(ssh)


def main() -> int:
    ssh = connect()
    upload_core(ssh)
    deadline = time.time() + MAX_HOURS * 3600
    last_fix = 0.0
    streak = 0
    report_path = ROOT / "logs" / "watch_5_rounds_result.json"

    while time.time() < deadline:
        if not listener_ok(ssh) or visual_bad(ssh):
            if time.time() - last_fix > 45:
                fix_if_broken(ssh)
                last_fix = time.time()

        tail = run(ssh, f"tail -n 8000 {LOG}")
        open_rids, img_rids, issues = parse_log_events(tail)
        streak, seq = streak_ok(open_rids, img_rids)
        print(
            f"[watch] {datetime.now(timezone.utc).strftime('%H:%M:%S')} "
            f"streak={streak}/{NEED_STREAK} open={sorted(open_rids)[-5:]} img={sorted(img_rids)[-5:]}",
            flush=True,
        )

        if streak >= NEED_STREAK:
            rc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "confirm_e2e.py")],
                cwd=ROOT,
            ).returncode
            if rc == 0:
                result = {
                    "ok": True,
                    "streak": streak,
                    "rounds": seq[-NEED_STREAK:],
                    "utc": datetime.now(timezone.utc).isoformat(),
                }
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(result, ensure_ascii=False))
                ssh.close()
                return 0

        recent_skip = [i for i in issues if "跳过公告" in i or "不在群" in i]
        if recent_skip and time.time() - last_fix > 60:
            fix_if_broken(ssh)
            last_fix = time.time()

        time.sleep(POLL_SEC)

    ssh.close()
    print(json.dumps({"ok": False, "reason": "timeout", "streak": streak}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
