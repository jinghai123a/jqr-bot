#!/usr/bin/env python3
"""生成 NoCloud ISO → 挂 CD → 重启 guest → 等 SSH。"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(r"C:\w49-edge-lab")
VMX = LAB / "w49-edge-lab.vmx"
ISO_OUT = LAB / "cidata-ssh.iso"
VMRUN = Path(r"C:\Users\haijin\VMware\Installation\vmrun.exe")
VM_HOST = "192.168.159.130"
VM_USER = "bot"
VM_PASS = "w49-edge-lab"

META = """instance-id: w49-ssh-fix-001
local-hostname: w49-edge-lab
"""

USER_DATA = """#cloud-config
runcmd:
  - bash -lc "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq"
  - bash -lc "export DEBIAN_FRONTEND=noninteractive; apt-get install -y openssh-server open-vm-tools open-vm-tools-desktop"
  - bash -lc "systemctl enable --now ssh"
  - bash -lc "echo w49-ssh-ready > /var/log/w49-ssh-ready"
"""


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "timeout"


def build_iso() -> None:
    from io import BytesIO

    import pycdlib

    if ISO_OUT.is_file():
        ISO_OUT.unlink()
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="cidata")
    meta = BytesIO(META.encode())
    user = BytesIO(USER_DATA.encode())
    iso.add_fp(meta, len(META.encode()), iso_path="/METADATA.;1", rr_name="meta-data")
    iso.add_fp(user, len(USER_DATA.encode()), iso_path="/USERDATA.;1", rr_name="user-data")
    iso.write(str(ISO_OUT))
    iso.close()
    print(f"[nocloud] wrote {ISO_OUT} ({ISO_OUT.stat().st_size} bytes)")


def patch_vmx() -> None:
    text = VMX.read_text(encoding="utf-8", errors="replace")
    iso_path = str(ISO_OUT).replace("\\", "\\\\")
    if "ide1:1.present" not in text:
        text += (
            f'\nide1:1.present = "TRUE"\n'
            f'ide1:1.fileName = "{iso_path}"\n'
            f'ide1:1.deviceType = "cdrom-image"\n'
            f'ide1:1.autodetect = "TRUE"\n'
        )
    else:
        text = re.sub(
            r'ide1:1\.fileName = ".*?"',
            f'ide1:1.fileName = "{iso_path}"',
            text,
            count=1,
        )
    VMX.write_text(text, encoding="utf-8")
    print("[nocloud] vmx cdrom ide1:1 attached")


def reboot_vm() -> None:
    rc, out = run([str(VMRUN), "list"])
    running = str(VMX) in out
    if running:
        print("[nocloud] soft reset...")
        run([str(VMRUN), "reset", str(VMX)], 60)
    else:
        print("[nocloud] start nogui...")
        run([str(VMRUN), "start", str(VMX), "nogui"], 120)
    time.sleep(15)


def wait_ssh(timeout_sec: int = 600) -> bool:
    try:
        import paramiko
    except ImportError:
        print("pip install paramiko")
        return False
    deadline = time.time() + timeout_sec
    n = 0
    while time.time() < deadline:
        n += 1
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=8)
            out = c.exec_command("test -f /var/log/w49-ssh-ready && echo READY")[1].read().decode()
            c.close()
            if "READY" in out:
                print(f"[nocloud] SSH OK + cloud-init marker ({n})")
                return True
            print(f"[nocloud] SSH up, waiting cloud-init ({n})")
        except Exception as exc:
            if n % 6 == 0:
                print(f"[nocloud] wait ssh... {exc}")
        time.sleep(10)
    return False


def main() -> int:
    build_iso()
    patch_vmx()
    reboot_vm()
    if wait_ssh():
        print("[nocloud] SUCCESS")
        return 0
    print("[nocloud] FAIL: SSH not ready")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
