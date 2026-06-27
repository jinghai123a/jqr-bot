#!/usr/bin/env python3
"""双云机：只保留 55M(wuwu) + ADB Keyboard，其余第三方 App 全部卸载。"""
from __future__ import annotations

import re
import time

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"

# 精确保留
KEEP_EXACT = frozenset({
    "com.android.adbkeyboard",
    "com.zx.adbkeyboard",
})

# 前缀保留（55M 包名 wuwu.*）
KEEP_PREFIX = ("wuwu.",)

# 优先卸载（Root/探针/乱点/多余 IME）
PRIORITY_UNINSTALL = (
    "com.topjohnwu.magisk",
    "io.github.huskydg.magisk",
    "io.github.vvb2060.magisk",
    "com.kitsune.magisk",
    "com.w49.chatprobe",
    "com.tengu.sharetoclipboard",
    "com.osfans.trime",
    "dev.patrickgold.florisboard",
    "com.github.uiautomator",
    "com.github.uiautomator.test",
    "com.github.uiautomator.test.uiautomator",
)


def run(ssh: paramiko.SSHClient, cmd: str, t: int = 180) -> str:
    chan = ssh.get_transport().open_session()
    chan.settimeout(t)
    chan.exec_command(cmd)
    buf = b""
    deadline = time.time() + t
    while time.time() < deadline:
        if chan.recv_ready():
            buf += chan.recv(8192)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(8192)
            break
        time.sleep(0.1)
    return buf.decode("utf-8", "replace")


def pick_serial(ssh: paramiko.SSHClient, port: str) -> str | None:
    for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
        out = run(ssh, f"adb -s {host} shell echo OK 2>/dev/null", 15)
        if "OK" in out:
            return host
    return None


def keep_pkg(pkg: str) -> bool:
    if pkg in KEEP_EXACT:
        return True
    return any(pkg.startswith(p) for p in KEEP_PREFIX)


def list_third_party(ssh: paramiko.SSHClient, serial: str) -> list[str]:
    out = run(ssh, f"adb -s {serial} shell pm list packages -3 2>/dev/null", 60)
    pkgs: list[str] = []
    for line in out.splitlines():
        m = re.match(r"package:(.+)", line.strip())
        if m:
            pkgs.append(m.group(1).strip())
    return sorted(set(pkgs))


def uninstall_pkg(ssh: paramiko.SSHClient, serial: str, pkg: str) -> str:
    cmd = (
        f"adb -s {serial} shell pm uninstall --user 0 {pkg} 2>&1; "
        f"adb -s {serial} uninstall {pkg} 2>&1"
    )
    return run(ssh, cmd, 45).strip().replace("\n", " | ")[:120]


def purge_device(ssh: paramiko.SSHClient, serial: str, label: str) -> None:
    print(f"\n=== {label} {serial} ===")
    installed = list_third_party(ssh, serial)
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
            tag = "KEEP-SKIP" if keep_pkg(pkg) else "UNINSTALL"
            if tag == "KEEP-SKIP":
                continue
            res = uninstall_pkg(ssh, serial, pkg)
            print(f"  - {pkg}: {res}")

    print(run(ssh, f"""
adb -s {serial} shell settings put secure enabled_accessibility_services '' 2>/dev/null || true
adb -s {serial} shell settings put secure accessibility_enabled 0 2>/dev/null || true
adb -s {serial} shell ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null || true
adb -s {serial} shell ime set com.android.adbkeyboard/.AdbIME 2>/dev/null || true
adb -s {serial} shell rm -rf /data/local/tmp/chatprobe.apk /data/local/tmp/trime.apk /data/local/tmp/florisboard.apk 2>/dev/null || true
adb -s {serial} shell pm list packages -3 2>/dev/null
""", 90))


def read_ports(ssh: paramiko.SSHClient) -> tuple[str, str]:
    env = run(ssh, f"grep -E 'BOT_LISTENER_ADB_PORT|BOT_CLICKER_ADB_PORT' {R}/config/bot-start.env", 10)
    rport, lport = "60478", "56121"
    for line in env.splitlines():
        if "LISTENER" in line and "=" in line:
            rport = line.split("=", 1)[1].strip()
        if "CLICKER" in line and "=" in line:
            lport = line.split("=", 1)[1].strip()
    return rport, lport


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)

    rport, lport = read_ports(ssh)
    rs = pick_serial(ssh, rport)
    ls = pick_serial(ssh, lport)
    if rs:
        purge_device(ssh, rs, "右机 LISTENER")
    else:
        print(f"WARN: 右机离线 port={rport}")
    if ls:
        purge_device(ssh, ls, "左机 CLICKER")
    else:
        print(f"WARN: 左机离线 port={lport}")

    print("\n=== restart bot ===")
    print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -10", 120))
    ssh.close()
    print("\ndone purge_unused_apps")


if __name__ == "__main__":
    main()
