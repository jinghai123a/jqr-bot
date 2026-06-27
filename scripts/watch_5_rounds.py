#!/usr/bin/env python3
"""盯盘：连续 5 期「开局公告 pipe + 左机批量发图」均成功才 exit 0。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops import load_vps_config  # noqa: E402
from bot_ops.clicker_watch import upload_daemon_assets  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402

NEED_STREAK = 5
POLL_SEC = 20
MAX_HOURS = 6


def parse_log_events(text: str) -> tuple[set[int], set[int], list[str]]:
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


def main() -> int:
    try:
        config = load_vps_config(ROOT)
    except RuntimeError as ex:
        print(f"[FAIL] VPS: {ex}")
        return 1

    r = config.bot_root
    log_path = f"{r}/logs/bot.log"
    report_path = ROOT / "logs" / "watch_5_rounds_result.json"

    with VpsSSH(config) as ssh:
        upload_daemon_assets(
            ssh,
            [
                (ROOT / "bot_55chat_daemon.py", "bot_55chat_daemon.py"),
                (ROOT / "scripts" / "recover_listener_now.py", "scripts/recover_listener_now.py"),
                (ROOT / "scripts" / "vmos_visual_monitor.py", "scripts/vmos_visual_monitor.py"),
                (ROOT / "scripts" / "confirm_e2e.py", "scripts/confirm_e2e.py"),
                (ROOT / "scripts" / "fix_until_green.py", "scripts/fix_until_green.py"),
            ],
            bot_root=r,
        )

        def listener_ok() -> bool:
            out = ssh.run(
                f"""python3 - <<'PY'
import os, sys
sys.path.insert(0, "{r}")
os.chdir("{r}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="127.0.0.1:{config.listener_adb_port}"
bot={{"id":"bot-4"}}
if hasattr(d, "listener_in_group_for_send"):
    root=d.ui_hierarchy(serial)
    grp=d.listener_in_group_for_send(root, bot, serial)
else:
    grp=False
print("OK" if grp and d.is_group_chat_activity(serial) else "NO")
PY""",
                60,
            )
            return "OK" in out

        def visual_bad() -> list[str]:
            out = ssh.run(f"python3 {r}/scripts/vmos_visual_monitor.py --both --once 2>&1", 45)
            bad = []
            for line in out.splitlines():
                m = re.search(r"(clicker|listener)\s+\S+\s+state=(\w+)", line)
                if not m:
                    continue
                role, st = m.group(1), m.group(2)
                if st in ("launcher", "webview", "offline", "other") or st != "target_group":
                    bad.append(f"{role}={st}")
            return bad

        def recover() -> None:
            ssh.run(f"cd {r} && python3 scripts/recover_listener_now.py 2>&1", 120)

        def fix_if_broken() -> None:
            if listener_ok() and not visual_bad():
                return
            recover()
            time.sleep(6)
            if not listener_ok():
                ssh.run(f"bash {r}/scripts/restart-55chat-bot.sh 2>&1 | tail -2", 120)
                time.sleep(18)
                recover()

        deadline = time.time() + MAX_HOURS * 3600
        last_fix = 0.0
        streak = 0

        while time.time() < deadline:
            if not listener_ok() or visual_bad():
                if time.time() - last_fix > 45:
                    fix_if_broken()
                    last_fix = time.time()

            tail = ssh.run(f"tail -n 8000 {log_path}")
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
                    return 0

            recent_skip = [i for i in issues if "跳过公告" in i or "不在群" in i]
            if recent_skip and time.time() - last_fix > 60:
                fix_if_broken()
                last_fix = time.time()

            time.sleep(POLL_SEC)

    print(json.dumps({"ok": False, "reason": "timeout", "streak": streak}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
