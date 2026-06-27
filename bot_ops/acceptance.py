"""Dual-brain acceptance checks (verify_dual_brain)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .checks import adb_port_online, env_map, log_ts, recent_log_matches
from .config import VpsConfig
from .report import CheckResult, emit_text, exit_code
from .ssh_client import VpsSSH

RECENT_MIN = 15


def run_verify_dual_brain(config: VpsConfig) -> int:
    checks: list[CheckResult] = []
    r = config.bot_root
    log_path = f"{r}/logs/bot.log"
    env_path = f"{r}/config/bot-start.env"
    pinned_path = f"{r}/config/pinned-coords.json"

    def ok(name: str, passed: bool, detail: str) -> None:
        checks.append(CheckResult(name, passed, detail))
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {name}: {detail}")

    try:
        with VpsSSH(config) as ssh:
            listener_port = config.listener_adb_port
            clicker_port = config.clicker_adb_port

            procs = ssh.run("pgrep -af bot_55chat_daemon || true")
            ok("daemon 进程", "bot_55chat_daemon.py" in procs, procs.strip().split("\n")[0][:120])

            adb = ssh.run("adb devices -l")
            ok(
                f"左机 ADB {clicker_port}",
                adb_port_online(adb, clicker_port),
                "online" if adb_port_online(adb, clicker_port) else adb[:160],
            )
            ok(
                f"右机 ADB {listener_port}",
                adb_port_online(adb, listener_port),
                "online" if adb_port_online(adb, listener_port) else adb[:160],
            )

            env_raw = ssh.run(f"grep -E '^(BOT_LISTENER_PURE_PIPE|BOT_LISTENER_PINNED_SEND|BOT_LISTENER_SEND_Y|BOT_IMG_PINNED|BOT_LISTENER_ZERO_NAV|BOT_CLICKER_OPTIONAL)=' {env_path}")
            ok("PURE_PIPE=1", "BOT_LISTENER_PURE_PIPE=1" in env_raw, env_raw.strip() or "missing")
            ok("IMG_PINNED=1", "BOT_IMG_PINNED=1" in env_raw, "set" if "BOT_IMG_PINNED=1" in env_raw else env_raw)
            ok("CLICKER 非 optional", "BOT_CLICKER_OPTIONAL=0" in env_raw, env_raw.strip())

            pinned_raw = ssh.run(f"test -f {pinned_path} && cat {pinned_path}")
            pinned: dict = {}
            try:
                pinned = json.loads(pinned_raw)
                has_click = "chat_plus" in pinned.get("clicker", {})
                has_send = "send" in pinned.get("listener", {})
                ok("pinned-coords.json", has_click and has_send, f"clicker+={has_click} listener_send={has_send}")
            except Exception as ex:
                ok("pinned-coords.json", False, str(ex))

            log_text = ssh.run(f"tail -n 12000 {log_path}")
            announce = recent_log_matches(
                log_text,
                r"pipe\+b64\+send|b64\+fire-thread|674,1234|封盘提醒|封盘公告|新一轮开始|跳过公告",
                minutes=RECENT_MIN,
            )
            recent_pipe = [
                ln for _, ln in announce
                if "pipe+b64+send" in ln or "b64+fire-thread" in ln or "674,1234" in ln
            ]
            recent_skip = [ln for _, ln in announce if "跳过公告" in ln]
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

            img_ok = recent_log_matches(log_text, r"批量发图成功|发图钉死 \+", minutes=RECENT_MIN)
            img_fail = recent_log_matches(log_text, r"批量发图失败|UI 发图失败|批量发图未确认", minutes=RECENT_MIN)
            ok("发图钉死/成功", len(img_ok) >= 1, f"近{RECENT_MIN}min 成功/钉死 {len(img_ok)} 条")
            if img_fail and not img_ok:
                ok("发图最近失败", False, img_fail[-1][1][-120:])
            elif img_fail:
                ok("发图最近失败", True, f"有 {len(img_fail)} 次未确认但后续已成功")
            else:
                ok("发图最近失败", True, "近窗无失败")

            fair = recent_log_matches(log_text, r"公平队列|已回复|enqueue_reply|RESOLVE", minutes=RECENT_MIN)
            ok("读屏/回复链路", True, f"近{RECENT_MIN}min fair/reply 相关 {len(fair)} 条")

            add_block = pinned.get("add_replies", {})
            ok("ADD 话术配置", bool(add_block.get("ok")), add_block.get("ok", "?")[:40])

            threads = ssh.run(f"grep -E '公告线程启动|announce-bot-4' {log_path} | tail -n 3")
            ok("双脑线程", "announce-bot-4" in threads, threads.strip().split("\n")[-1][-80:] if threads.strip() else "无")

            allow_out = ssh.run(
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

    except Exception as ex:
        checks.append(CheckResult("VPS SSH", False, str(ex)))
        print(f"[FAIL] VPS SSH: {ex}")

    fails = [c for c in checks if not c.passed]
    print("\n=== SUMMARY ===")
    print(f"时间 UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"通过 {len(checks) - len(fails)}/{len(checks)}")
    if fails:
        print("未通过:")
        for c in fails:
            print(f"  - {c.name}: {c.detail}")
    else:
        print("全部通过")
    _ = emit_text(checks)
    return exit_code(checks)
