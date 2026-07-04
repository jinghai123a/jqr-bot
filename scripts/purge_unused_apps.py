#!/usr/bin/env python3
"""双云机：只保留 55M(wuwu) + ADB Keyboard，其余第三方 App 卸载（在 VPS 上执行）。"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

BOT_ROOT = Path(os.environ.get("BOT_ROOT", "/home/bot/55chat-bot"))

KEEP_EXACT = frozenset({
    "com.android.adbkeyboard",
    "com.zx.adbkeyboard",
})
KEEP_PREFIX = ("wuwu.",)
PRIORITY_UNINSTALL = (
    "com.topjohnwu.magisk",
    "io.github.huskydg.magisk",
    "io.github.vvb2060.magisk",
    "com.kitsune.magisk",
    "com.w49.chatprobe",
    "com.osfans.trime",
    "com.tengu.sharetoclipboard",
    "dev.patrickgold.florisboard",
    "com.github.uiautomator",
    "com.github.uiautomator.test",
    "com.github.uiautomator.test.uiautomator",
)


def _sh(cmd: str, timeout: int = 120) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def keep_pkg(pkg: str) -> bool:
    if pkg in KEEP_EXACT:
        return True
    return any(pkg.startswith(p) for p in KEEP_PREFIX)


def read_ports() -> tuple[str, str]:
    env = BOT_ROOT / "config" / "bot-start.env"
    rport, lport = "58433", "52840"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("BOT_LISTENER_ADB_PORT="):
                rport = line.split("=", 1)[1].strip()
            elif line.startswith("BOT_CLICKER_ADB_PORT="):
                lport = line.split("=", 1)[1].strip()
    return rport, lport


def pick_serial(port: str) -> str | None:
    for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
        if "OK" in _sh(f"adb -s {host} shell echo OK 2>/dev/null", 15):
            return host
    return None


def list_third_party(serial: str) -> list[str]:
    out = _sh(f"adb -s {serial} shell pm list packages -3 2>/dev/null", 60)
    pkgs: list[str] = []
    for line in out.splitlines():
        m = re.match(r"package:(.+)", line.strip())
        if m:
            pkgs.append(m.group(1).strip())
    return sorted(set(pkgs))


def uninstall_pkg(serial: str, pkg: str) -> str:
    return _sh(
        f"adb -s {serial} shell pm uninstall --user 0 {pkg} 2>&1; "
        f"adb -s {serial} uninstall {pkg} 2>&1",
        45,
    ).replace("\n", " | ")[:120]


def purge_device(serial: str, label: str) -> None:
    print(f"\n=== {label} {serial} ===")
    installed = list_third_party(serial)
    print(f"第三方包 {len(installed)} 个: {', '.join(installed) or '(无)'}")

    todo: list[str] = []
    for pkg in PRIORITY_UNINSTALL:
        if pkg in installed:
            todo.append(pkg)
    for pkg in installed:
        if pkg in todo or keep_pkg(pkg):
            continue
        todo.append(pkg)

    if not todo:
        print("无需卸载")
    else:
        for pkg in todo:
            if keep_pkg(pkg):
                continue
            print(f"  - {pkg}: {uninstall_pkg(serial, pkg)}")

    print(_sh(f"""
adb -s {serial} shell settings put secure enabled_accessibility_services '' 2>/dev/null || true
adb -s {serial} shell settings put secure accessibility_enabled 0 2>/dev/null || true
adb -s {serial} shell ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null || true
adb -s {serial} shell ime set com.android.adbkeyboard/.AdbIME 2>/dev/null || true
adb -s {serial} shell rm -rf /data/local/tmp/chatprobe.apk /data/local/tmp/trime.apk 2>/dev/null || true
adb -s {serial} shell pm list packages -3 2>/dev/null
""", 90))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-restart", action="store_true")
    args = ap.parse_args()

    rport, lport = read_ports()
    rs = pick_serial(rport)
    ls = pick_serial(lport)
    if rs:
        purge_device(rs, "右机 LISTENER")
    else:
        print(f"WARN: 右机离线 port={rport}")
    if ls:
        purge_device(ls, "左机 CLICKER")
    else:
        print(f"WARN: 左机离线 port={lport}")

    if not args.no_restart:
        print("\n=== restart bot ===")
        print(_sh(f"bash {BOT_ROOT}/scripts/restart-55chat-bot.sh 2>&1 | tail -10", 120))
    print("\ndone purge_unused_apps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
