#!/usr/bin/env python3
"""双云机 + VPS：卸载乱点/粘贴/探针组件，删相关脚本，保留 55M + ADB Keyboard。"""
from __future__ import annotations

import os
import time

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

# 会点屏/乱导航/Root 弹窗的 App（保留 wuwu + adbkeyboard）
UNINSTALL_PKGS = (
    "io.github.huskydg.magisk",
    "com.topjohnwu.magisk",
    "com.kitsune.magisk",
    "com.github.uiautomator",
    "com.github.uiautomator.test",
    "com.w49.chatprobe",
    "com.tengu.sharetoclipboard",
    "com.osfans.trime",
    "dev.patrickgold.florisboard",
    "com.google.android.apps.work.clouddpc",
    "android.autoinstalls.config.transsion.device",
)

# 本地 + VPS 删除的指挥/试验脚本（glob 片段）
SCRIPT_GLOBS = (
    "*floris*",
    "*trime*",
    "setup-cloud-clipboard.sh",
    "setup-florisboard-ime.sh",
    "probe-55m-commit-content.py",
    "probe-55m-image-paths.py",
    "vps_start_left_ui_test.py",
    "vps_deploy_left_ui_send.py",
    "vps_retest_left_ui_image.py",
    "vps_tap_group_ui_send.py",
    "_tap_popup_btn.py",
    "_left_ui_send_once.py",
    "dual-auto-heal.py",
    "dual-monitor-1h.py",
    "return-to-group.py",
    "vps_trime_probe_setup.sh",
    "vps_trime_probe_setup.py",
    "vps_redeploy_listener.py",
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
        time.sleep(0.12)
    return buf.decode("utf-8", "replace")


def pick_serial(ssh: paramiko.SSHClient, port: str) -> str | None:
    for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
        out = run(ssh, f"adb -s {host} shell echo OK 2>/dev/null", 15)
        if "OK" in out:
            return host
    return None


def purge_device(ssh: paramiko.SSHClient, serial: str, label: str) -> None:
    print(f"\n=== {label} {serial} ===")
    for pkg in UNINSTALL_PKGS:
        print(run(ssh, f"adb -s {serial} uninstall {pkg} 2>/dev/null; "
                     f"adb -s {serial} shell pm uninstall --user 0 {pkg} 2>/dev/null; true", 30).strip()[:80])
    print(run(ssh, f"""
adb -s {serial} shell rm -rf /data/local/tmp/chatprobe.apk /data/local/tmp/trime.apk /data/local/tmp/florisboard.apk /sdcard/Download/floris_*.png /sdcard/Download/bot_paste_*.png 2>/dev/null || true
adb -s {serial} shell settings put secure enabled_accessibility_services '' 2>/dev/null || true
adb -s {serial} shell settings put secure accessibility_enabled 0 2>/dev/null || true
adb -s {serial} shell ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null || true
adb -s {serial} shell ime set com.android.adbkeyboard/.AdbIME 2>/dev/null || true
adb -s {serial} shell pm list packages 2>/dev/null | grep -iE 'trime|floris|probe|share|wuwu|adbkeyboard' || true
""", 60))


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)

    sftp = ssh.open_sftp()
    sftp.put(os.path.join(ROOT, "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
    sftp.put(os.path.join(BASE, "patch_speed_env.py"), f"{R}/scripts/patch_speed_env.py")
    sftp.put(os.path.join(BASE, "purge_tap_stack.py"), f"{R}/scripts/purge_tap_stack.py")
    pinned = os.path.join(ROOT, "config", "pinned-coords.json")
    if os.path.isfile(pinned):
        sftp.put(pinned, f"{R}/config/pinned-coords.json")
    sftp.close()

    print("=== stop heal/monitor ===")
    print(run(ssh, "pkill -f dual-auto-heal.py; pkill -f dual-monitor-1h.py; pkill -f poll_dual_monitor; true", 15))

    print("=== delete tap scripts on VPS ===")
    globs = " ".join(f'"{g}"' for g in SCRIPT_GLOBS)
    print(run(ssh, f"cd {R}/scripts && for g in {globs}; do rm -f $g 2>/dev/null; done; ls -1 | grep -iE 'floris|trime|tap_group|left_ui|paste|clipboard-setup|dual-auto|dual-monitor' || echo '(clean)'", 20))

    print("=== patch env ===")
    print(run(ssh, f"python3 {R}/scripts/patch_speed_env.py", 20))
    print(run(ssh, f"grep -q '^BOT_PROBE_ENABLED=' {R}/config/bot-start.env && "
                 f"sed -i 's/^BOT_PROBE_ENABLED=.*/BOT_PROBE_ENABLED=0/' {R}/config/bot-start.env || "
                 f"echo BOT_PROBE_ENABLED=0 >> {R}/config/bot-start.env", 10))
    print(run(ssh, f"grep -q '^BOT_IMG_SEND_MODE=' {R}/config/bot-start.env && "
                 f"sed -i 's/^BOT_IMG_SEND_MODE=.*/BOT_IMG_SEND_MODE=ui/' {R}/config/bot-start.env || "
                 f"echo BOT_IMG_SEND_MODE=ui >> {R}/config/bot-start.env", 10))

    print("=== tunnels ===")
    print(run(ssh, f"bash {R}/scripts/tunnel-right.sh 2>&1 | tail -2; bash {R}/scripts/tunnel-left.sh 2>&1 | tail -2", 120))

    env = run(ssh, f"grep -E 'BOT_LISTENER_ADB_PORT|BOT_CLICKER_ADB_PORT' {R}/config/bot-start.env", 10)
    rport = "54936"
    lport = "52840"
    for line in env.splitlines():
        if "LISTENER" in line and "=" in line:
            rport = line.split("=", 1)[1].strip()
        if "CLICKER" in line and "=" in line:
            lport = line.split("=", 1)[1].strip()

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
    print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -12", 120))
    time.sleep(6)
    print(run(ssh, "adb devices -l | grep -E '52718|52840|54936|60478' || true", 20))
    print(run(ssh, f"tail -8 {R}/logs/bot.log", 15))
    ssh.close()
    print("\ndone purge_tap_stack")


if __name__ == "__main__":
    main()
