#!/usr/bin/env python3
"""上传并安装 68-helper（设备码工具）到 VPS。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

LOCAL = Path(
    os.environ.get(
        "LOCAL_68_HELPER",
        r"C:\Users\haijin\Downloads\68-helper-26.7.4-setup-win-x64.exe",
    )
)
REMOTE_DIR = "/opt/55chat"
REMOTE = f"{REMOTE_DIR}/68-helper-26.7.4-setup-win-x64.exe"
PREFIX = "/home/bot/.wine55m"


def upload_if_needed(ssh: VpsSSH) -> None:
    if not LOCAL.is_file():
        raise SystemExit(f"缺少安装包: {LOCAL}")
    size = LOCAL.stat().st_size
    cur = ssh.run(f"stat -c%s '{REMOTE}' 2>/dev/null || echo 0", 20).strip()
    if cur.isdigit() and int(cur) == size:
        print(f"skip upload (same size {size})")
        return
    print(f"upload {LOCAL.name} ({size} bytes)...")
    ssh.run(f"mkdir -p {REMOTE_DIR}/logs && chown bot:bot {REMOTE_DIR}", 15)
    ssh.sftp_put(str(LOCAL), REMOTE)
    ssh.run(f"chown bot:bot '{REMOTE}'", 15)


def main() -> int:
    os.environ.setdefault("VPS_PASSWORD", "w49-55m-vnc")
    cfg = load_vps_config(ROOT)
    print(f"VPS {cfg.user}@{cfg.host}")

    install_sh = f"""#!/bin/bash
set -e
PREFIX={PREFIX}
INSTALLER='{REMOTE}'
LOG={REMOTE_DIR}/logs/68-helper-install.log

apt-get install -y -qq xdotool wmctrl 2>/dev/null | tail -1

# 停旧 wine 避免冲突
su - bot -c 'export WINEPREFIX=$PREFIX; wineserver -k' 2>/dev/null || true
sleep 2

echo "=== launch GUI installer ==="
su - bot -c "export DISPLAY=:0 WINEPREFIX=$PREFIX; nohup wine-stable \\"$INSTALLER\\" >>$LOG 2>&1 &"
sleep 12

pgrep -af '68-helper|setup' | grep -v pgrep | head -5 || true
su - bot -c 'export DISPLAY=:0; wmctrl -l 2>/dev/null' | head -10

# 若已装过，直接找 exe
HELPER=""
for cand in \\
  "$PREFIX/drive_c/users/bot/AppData/Local/Programs/68-helper/68-helper.exe" \\
  "$PREFIX/drive_c/users/bot/AppData/Local/Programs/68-helper/helper.exe" \\
  "$PREFIX/drive_c/Program Files/68-helper/68-helper.exe" \\
  "$PREFIX/drive_c/Program Files (x86)/68-helper/68-helper.exe"; do
  [ -f "$cand" ] && HELPER="$cand" && break
done
if [ -z "$HELPER" ]; then
  HELPER=$(find "$PREFIX/drive_c" -iname '*helper*.exe' 2>/dev/null | grep -vi uninstall | head -1 || true)
fi

if [ -n "$HELPER" ]; then
  echo "=== launch helper: $HELPER ==="
  su - bot -c "export DISPLAY=:0 WINEPREFIX=$PREFIX; nohup wine-stable \\"$HELPER\\" >>{REMOTE_DIR}/logs/68-helper.log 2>&1 &"
  sleep 5
  su - bot -c 'export DISPLAY=:0; wmctrl -l' | grep -i helper || true
fi

echo DONE
"""

    with VpsSSH(cfg) as ssh:
        upload_if_needed(ssh)
        ssh.run(
            "cat > /tmp/install_68helper.sh << 'EOF'\n" + install_sh + "\nEOF\nchmod +x /tmp/install_68helper.sh",
            20,
        )
        out = ssh.run("bash /tmp/install_68helper.sh 2>&1", 120)
        print(out[-4000:] if len(out) > 4000 else out)

    print("\n=== W49 ===")
    print("noVNC/RDP 进桌面 → 完成 68-helper 安装向导")
    print("打开后复制【设备码】发给客服 @jenkins_pro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
