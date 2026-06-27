"""Live cloud verification — ADB screen + screenshot + send loopback."""
from __future__ import annotations

import base64
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko

from .config import VpsConfig
from .report import CheckResult, exit_code
from .ssh_client import VpsSSH


def run_live_verify(
    config: VpsConfig,
    *,
    art_dir: Path | None = None,
    right_serial: str | None = None,
    left_serial: str | None = None,
) -> int:
    checks: list[CheckResult] = []
    r = config.bot_root
    right = right_serial or f"127.0.0.1:{config.listener_adb_port}"
    left = left_serial or f"localhost:{config.clicker_adb_port}"
    art = art_dir or (Path(__file__).resolve().parents[1] / "artifacts" / "live-verify")

    def ok(name: str, passed: bool, detail: str) -> None:
        checks.append(CheckResult(name, passed, detail))
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    def adb_cmd(ssh: VpsSSH, serial: str, shell_cmd: str, t: int = 45) -> str:
        return ssh.run(f"adb -s {serial} {shell_cmd}", t)

    def pull_png(ssh: VpsSSH, serial: str, label: str) -> Path | None:
        art.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%H%M%S")
        remote = f"/tmp/afu_{label}_{ts}.png"
        local = art / f"{label}_{ts}.png"
        ssh.run(f"adb -s {serial} exec-out screencap -p > {remote} 2>/dev/null", 35)
        try:
            ssh.sftp_get(remote, str(local))
            ssh.run(f"rm -f {remote}", 10)
            return local if local.is_file() and local.stat().st_size > 800 else None
        except Exception as ex:
            ok(f"截图 {label}", False, str(ex))
            return None

    def focus_activity(ssh: VpsSSH, serial: str) -> str:
        out = adb_cmd(ssh, serial, 'shell "dumpsys window displays 2>/dev/null | grep mCurrentFocus | head -1"', 20)
        m = re.search(r"(\S+/[\w.]+)\}", out)
        return m.group(1) if m else out.strip()[:120]

    def draft_text(ssh: VpsSSH, serial: str) -> str:
        adb_cmd(ssh, serial, "shell uiautomator dump /data/local/tmp/v.xml 2>/dev/null", 35)
        xml = adb_cmd(ssh, serial, "shell cat /data/local/tmp/v.xml 2>/dev/null", 15)
        m = re.search(r'editTextMessage[^>]*text="([^"]*)"', xml)
        if m:
            return m.group(1)
        m2 = re.search(r"editTextMessage", xml)
        return "(空)" if m2 else "无输入框"

    def right_send_probe(ssh: VpsSSH) -> None:
        test = f"阿福实况验收{int(time.time()) % 10000}"
        b64 = base64.b64encode(test.encode("utf-8")).decode("ascii")
        ssh.run(f'adb -s {right} shell am broadcast -a ADB_INPUT_B64 --es msg "{b64}"', 15)
        time.sleep(0.4)
        before = draft_text(ssh, right)
        adb_cmd(ssh, right, "shell input tap 674 1234", 10)
        time.sleep(0.8)
        after = draft_text(ssh, right)
        cleared = after in ("", "(空)", "输入消息") or test not in after
        ok("右机 b64+tap 发送环回", cleared, f"before={before[:24]!r} after={after[:24]!r}")

    def left_attach_probe(ssh: VpsSSH) -> None:
        act = focus_activity(ssh, left)
        if "GroupChatActivity" not in act:
            ok("左机在群聊", False, act)
            return
        ok("左机在群聊", True, act.split("/")[-1])

        ssh.run(f"adb -s {left} shell cmd input_method hide", 10)
        ssh.run(f"adb -s {left} shell input keyevent 111", 8)
        time.sleep(0.35)

        def dump_xml() -> str:
            ssh.run(f"adb -s {left} shell uiautomator dump /data/local/tmp/v.xml 2>/dev/null", 50)
            time.sleep(0.2)
            return ssh.run(f"adb -s {left} shell cat /data/local/tmp/v.xml 2>/dev/null", 20)

        xml = dump_xml()
        iv = xml.count("ImageView")
        menu_open = "图片" in xml or ("拍摄" in xml and "红包" in xml) or iv >= 6
        if menu_open:
            ok("左机附件栏", True, "已展开(无需再点+)")
        else:
            ssh.run(f"adb -s {left} shell input tap 45 1234", 12)
            time.sleep(0.8)
            xml = dump_xml()
            iv = xml.count("ImageView")
            menu_open = "图片" in xml or iv >= 6
            ok("左机 + 展开附件栏", menu_open, f"ImageView={iv}" if menu_open else xml[:80])

        if menu_open:
            ssh.run(f"adb -s {left} shell input tap 90 787", 12)
            time.sleep(1.0)
            xml2 = dump_xml()
            iv2 = xml2.count("ImageView")
            gallery = "/9" in xml2.replace(" ", "") or "相册" in xml2 or "最近" in xml2 or iv2 >= 15
            ok("左机 点图片进相册", gallery, f"ImageView={iv2}" if gallery else xml2[:100])
            ssh.run(f"adb -s {left} shell input keyevent 111", 8)
            ssh.run(f"adb -s {left} shell input tap 34 86", 8)

    def daemon_threads(ssh: VpsSSH) -> None:
        raw = ssh.run(f"tail -500 {r}/logs/bot.log")
        procs = ssh.run("pgrep -af 'bot_55chat|ui-collect|fire' || true")
        for name, hit in [
            ("ui-collect", "ui-collect" in raw or "ui-collect" in procs),
            ("listener-fire", "fire 线程点发送" in raw or "fire-thread" in raw),
            ("clicker-fire", "左机 fire" in raw or "clicker-fire" in procs),
            ("sender-bot-4", "sender-bot-4" in raw),
            ("clicker-img-bot-3", "clicker-img-bot-3" in raw),
        ]:
            ok(f"线程 {name}", hit, "已启动" if hit else "未见")

    print(f"=== 云机实况验收 UTC {datetime.now(timezone.utc).isoformat()} ===\n")
    try:
        with VpsSSH(config) as ssh:
            adb_out = ssh.run("adb devices -l")
            ok("右机 ADB online", right in adb_out and "device" in adb_out, right)
            ok("左机 ADB online", left in adb_out and "device" in adb_out, left)

            r_act = focus_activity(ssh, right)
            ok("右机在群聊", "GroupChatActivity" in r_act, r_act)

            r_png = pull_png(ssh, right, "right")
            ok("右机截图", r_png is not None, str(r_png) if r_png else "失败")

            l_png = pull_png(ssh, left, "left")
            ok("左机截图", l_png is not None, str(l_png) if l_png else "失败")

            right_send_probe(ssh)
            left_attach_probe(ssh)
            daemon_threads(ssh)
    except paramiko.SSHException as ex:
        ok("VPS SSH", False, str(ex))
    except Exception as ex:
        ok("VPS SSH", False, str(ex))

    fails = [c for c in checks if not c.passed]
    print(f"\n=== 结果 {len(checks) - len(fails)}/{len(checks)} PASS ===")
    if fails:
        for c in fails:
            print(f"  FAIL {c.name}: {c.detail}")
    else:
        print("云机实况全部通过")
    return exit_code(checks)
