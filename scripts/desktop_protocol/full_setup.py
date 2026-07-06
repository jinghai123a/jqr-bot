#!/usr/bin/env python3
"""一键：上传本机 55-im → VPS 桌面协议栈（VNC + Wine + WS 监控）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

BOT_ROOT = "/home/bot/55chat-bot"
DESKTOP = "/opt/55chat"
REMOTE_BOOT = f"{BOT_ROOT}/scripts/desktop_protocol/bootstrap_ubuntu.sh"

LOCAL_INSTALLER = Path(os.environ.get("LOCAL_55IM_SETUP", r"C:\Users\haijin\Downloads\55-im-1.7.1-win-x64-setup.exe"))
LOCAL_ZIP = Path(os.environ.get("LOCAL_55IM_ZIP", r"C:\Users\haijin\Downloads\55-im.zip"))

DEPLOY_FILES = [
    (ROOT / "scripts/desktop_protocol/bootstrap_ubuntu.sh", REMOTE_BOOT),
    (ROOT / "protocol/55ws-client/package.json", f"{BOT_ROOT}/protocol/55ws-client/package.json"),
    (ROOT / "protocol/55ws-client/watch.js", f"{BOT_ROOT}/protocol/55ws-client/watch.js"),
]


def _upload_if_needed(ssh: VpsSSH, local: Path, remote: str, min_size: int = 1_000_000) -> None:
    if not local.is_file():
        print(f"skip upload (missing): {local}")
        return
    size = local.stat().st_size
    cur = ssh.run(f"stat -c%s '{remote}' 2>/dev/null || echo 0", 15).strip()
    if cur.isdigit() and int(cur) >= min_size and int(cur) == size:
        print(f"skip upload (same size): {remote}")
        return
    print(f"upload {local.name} ({size} bytes) -> {remote}")
    ssh.run(f"mkdir -p '{Path(remote).parent.as_posix()}'", 15)
    ssh.sftp_put(str(local), remote)
    ssh.run(f"chown bot:bot '{remote}'", 15)


def main() -> int:
    cfg = load_vps_config(ROOT)
    print(f"VPS {cfg.user}@{cfg.host}")

    with VpsSSH(cfg) as ssh:
        ssh.run(
            f"mkdir -p {BOT_ROOT}/scripts/desktop_protocol {BOT_ROOT}/protocol/55ws-client {DESKTOP}/logs",
            20,
        )
        for local, remote in DEPLOY_FILES:
            ssh.sftp_put(str(local), remote)
        ssh.run(f"sed -i 's/\\r$//' {REMOTE_BOOT} && chmod +x {REMOTE_BOOT}", 15)

        remote_setup = f"{DESKTOP}/55-im-1.7.1-win-x64-setup.exe"
        _upload_if_needed(ssh, LOCAL_INSTALLER, remote_setup)
        if LOCAL_ZIP.is_file():
            _upload_if_needed(ssh, LOCAL_ZIP, f"{DESKTOP}/55-im.zip", min_size=50_000_000)

        print("=== bootstrap ===")
        env = (
            f"DESKTOP_ROOT={DESKTOP} BOT_ROOT={BOT_ROOT} "
            f"PROTO_ROOT=/home/bot/55chat-protocol"
        )
        out = ssh.run(f"{env} bash {REMOTE_BOOT} 2>&1", 1200)
        print(out[-6000:] if len(out) > 6000 else out)

        print("=== status ===")
        status = ssh.run(
            f"free -h | head -2; echo ---; "
            f"pgrep -a Xtigervnc | head -1; "
            f"pgrep -af 'setup.exe|im.exe|watch.js' | grep -v pgrep | head -8; "
            f"ss -lntp | grep -E '5901|5599' || echo ports:5901_vnc_only; "
            f"test -f {DESKTOP}/logs/WS_READY.flag && cat {DESKTOP}/logs/WS_READY.flag || echo WS_NOT_READY",
            30,
        )
        sys.stdout.buffer.write(status.encode("utf-8", errors="replace"))

    print("\n=== W49 VNC ===")
    print(f"  {cfg.host}:5901  密码 w49-55m-vnc")
    print("  安装器应在桌面 — 装完打开 55-im 登录，5599 自动就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
