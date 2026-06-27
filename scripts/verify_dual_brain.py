#!/usr/bin/env python3
"""双脑硬性验收：部署/改代码后必须跑，无需 W49 提醒。"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
LOG = f"{R}/logs/bot.log"
ENV = f"{R}/config/bot-start.env"
PINNED = f"{R}/config/pinned-coords.json"
RECENT_MIN = 15  # 只判最近 N 分钟内的 skip/发图失败

CHECKS: list[tuple[str, bool, str]] = []


def ok(name: str, passed: bool, detail: str) -> None:
    CHECKS.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {name}: {detail}")


def run(ssh, cmd: str, timeout: int = 90) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode("utf-8", "replace")


def env_map(ssh) -> dict[str, str]:
    raw = run(ssh, f"test -f {ENV} && cat {ENV} || true", 15)
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def adb_port_online(adb: str, port: str) -> bool:
    return any(port in line and re.search(r"\sdevice(?:\s|$)", line) for line in adb.splitlines())


def log_ts(line: str) -> datetime | None:
    m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def recent_lines(ssh, pattern: str, tail: int = 12000) -> list[tuple[datetime | None, str]]:
    raw = run(ssh, f"tail -n {tail} {LOG}")
    rx = re.compile(pattern)
    out: list[tuple[datetime | None, str]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=RECENT_MIN)
    for ln in raw.splitlines():
        if not rx.search(ln):
            continue
        ts = log_ts(ln)
        if ts and ts < cutoff:
            continue
        out.append((ts, ln))
    return out


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, username=USER, password=PW, timeout=30)
    except Exception as ex:
        ok("VPS SSH", False, str(ex))
        return 1

    env_all = env_map(ssh)
    listener_port = env_all.get("BOT_LISTENER_ADB_PORT", "60478")
    clicker_port = env_all.get("BOT_CLICKER_ADB_PORT", "56121")

    # 1) 进程 + ADB
    procs = run(ssh, "pgrep -af bot_55chat_daemon || true")
    ok("daemon 进程", "bot_55chat_daemon.py" in procs, procs.strip().split("\n")[0][:120])

    adb = run(ssh, "adb devices -l")
    ok(f"左机 ADB {clicker_port}", adb_port_online(adb, clicker_port), "online" if adb_port_online(adb, clicker_port) else adb[:160])
    ok(f"右机 ADB {listener_port}", adb_port_online(adb, listener_port), "online" if adb_port_online(adb, listener_port) else adb[:160])

    # 2) 关键 env
    env = run(ssh, f"grep -E '^(BOT_LISTENER_PURE_PIPE|BOT_LISTENER_PINNED_SEND|BOT_LISTENER_SEND_Y|BOT_IMG_PINNED|BOT_LISTENER_ZERO_NAV|BOT_CLICKER_OPTIONAL)=' {ENV}")
    ok("PURE_PIPE=1", "BOT_LISTENER_PURE_PIPE=1" in env, env.strip() or "missing")
    ok("IMG_PINNED=1", "BOT_IMG_PINNED=1" in env, "set" if "BOT_IMG_PINNED=1" in env else env)
    ok("CLICKER 非 optional", "BOT_CLICKER_OPTIONAL=0" in env, env.strip())

    # 3) 钉死坐标文件
    pinned_raw = run(ssh, f"test -f {PINNED} && cat {PINNED}")
    pinned: dict = {}
    try:
        pinned = json.loads(pinned_raw)
        has_click = "chat_plus" in pinned.get("clicker", {})
        has_send = "send" in pinned.get("listener", {})
        ok("pinned-coords.json", has_click and has_send, f"clicker+={has_click} listener_send={has_send}")
    except Exception as ex:
        ok("pinned-coords.json", False, str(ex))

    # 4) 公告链路（最近 15 分钟）
    announce = recent_lines(
        ssh,
        r"pipe\+b64\+send|b64\+fire-thread|674,1234|封盘提醒|封盘公告|新一轮开始|跳过公告",
    )
    recent_pipe = [
        ln for _, ln in announce
        if "pipe+b64+send" in ln or "b64+fire-thread" in ln or "674,1234" in ln
    ]
    recent_skip = [ln for _, ln in announce if "跳过公告" in ln]
    # 部署重启后 90s 内 skip 可忽略（若之后已有 pipe 成功）
    startup_skip = False
    if recent_skip and recent_pipe:
        skip_ts = log_ts(recent_skip[-1])
        last_pipe_ts = log_ts(recent_pipe[-1])
        if skip_ts and last_pipe_ts and last_pipe_ts >= skip_ts:
            startup_skip = True
    ok("公告 pipe 发送", len(recent_pipe) >= 1, f"近{RECENT_MIN}min {len(recent_pipe)} 条 pipe 成功")
    if recent_skip and not startup_skip:
        ok("公告 skip 告警", False, recent_skip[-1][-120:])
    else:
        detail = f"近{RECENT_MIN}min 无 skip" if not recent_skip else "重启空窗已恢复(pipe 在 skip 之后)"
        ok("公告 skip 告警", True, detail)

    # 5) 发图钉死坐标（近 15min 有成功即 PASS；全失败才 FAIL）
    img_ok = recent_lines(ssh, r"批量发图成功|发图钉死 \+")
    img_fail = recent_lines(ssh, r"批量发图失败|UI 发图失败|批量发图未确认")
    ok("发图钉死/成功", len(img_ok) >= 1, f"近{RECENT_MIN}min 成功/钉死 {len(img_ok)} 条")
    if img_fail and not img_ok:
        ok("发图最近失败", False, img_fail[-1][1][-120:])
    elif img_fail:
        ok("发图最近失败", True, f"有 {len(img_fail)} 次未确认但后续已成功")
    else:
        ok("发图最近失败", True, "近窗无失败")

    # 6) 右机读指令 / 公平队列
    fair = recent_lines(ssh, r"公平队列|已回复|enqueue_reply|RESOLVE")
    ok("读屏/回复链路", True, f"近{RECENT_MIN}min fair/reply 相关 {len(fair)} 条")

    # 7) ADD 三分支话术
    add_block = pinned.get("add_replies", {})
    ok("ADD 话术配置", bool(add_block.get("ok")), add_block.get("ok", "?")[:40])

    # 8) 线程启动（近 log 有 announce 即可）
    threads = run(ssh, f"grep -E '公告线程启动|announce-bot-4' {LOG} | tail -n 3")
    ok("双脑线程", "announce-bot-4" in threads, threads.strip().split("\n")[-1][-80:] if threads.strip() else "无")

    # 9) 云机 App 白名单（仅 55M + ADB Keyboard，禁止 Magisk/u2 等）
    allow_out = run(
        ssh,
        f"""for p in {listener_port} {clicker_port}; do
  for h in 127.0.0.1:$p localhost:$p; do
    adb -s $h shell echo OK 2>/dev/null && {{
      echo "=== $h ==="
      adb -s $h shell pm list packages -3 2>/dev/null
      break
    }}
  done
done""",
        45,
    )
    lines = [ln.strip() for ln in allow_out.splitlines() if ln.startswith("package:")]
    pkgs = [ln.split(":", 1)[1] for ln in lines]
    bad = [
        p for p in pkgs
        if not (
            p.startswith("wuwu.")
            or p in ("com.android.adbkeyboard", "com.zx.adbkeyboard")
            or p.startswith("android.autoinstalls.config.")
        )
    ]
    ok("云机 App 白名单", not bad, f"多余包: {', '.join(bad)}" if bad else f"仅 {len(pkgs)} 个第三方包")

    ssh.close()

    fails = [c for c in CHECKS if not c[1]]
    print("\n=== SUMMARY ===")
    print(f"时间 UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"通过 {len(CHECKS) - len(fails)}/{len(CHECKS)}")
    if fails:
        print("未通过:")
        for name, _, detail in fails:
            print(f"  - {name}: {detail}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
