#!/usr/bin/env python3
"""清空磁盘 + Subiquity autoinstall（含 openssh-server）→ 等 SSH。"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(r"C:\w49-edge-lab")
VMX = LAB / "w49-edge-lab.vmx"
VMDK = LAB / "w49-edge-lab.vmdk"
ISO_UBUNTU = Path(r"D:\ISO\ubuntu-24.04.4-desktop-amd64.iso")
ISO_SEED = LAB / "cidata-autoinstall.iso"
SEED_SRC = ROOT / "local_vm" / "autoinstall"
VMRUN = Path(r"C:\Users\haijin\VMware\Installation\vmrun.exe")
VDISK = Path(r"C:\Users\haijin\VMware\Installation\vmware-vdiskmanager.exe")
VMUSER = "bot"
VMPASS = "w49-edge-lab"


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "timeout"


def stop_vm() -> None:
    rc, out = run([str(VMRUN), "list"])
    if str(VMX) not in out:
        return
    print("[reinstall] stop hard...")
    run([str(VMRUN), "stop", str(VMX), "hard"], 120)
    time.sleep(3)


def recreate_disk() -> None:
    if VMDK.is_file():
        print("[reinstall] remove old vmdk...")
        VMDK.unlink(missing_ok=True)
        for p in LAB.glob("w49-edge-lab*.vmdk"):
            p.unlink(missing_ok=True)
    print("[reinstall] create 40GB vmdk...")
    rc, out = run([str(VDISK), "-c", "-s", "40GB", "-a", "lsilogic", "-t", "1", str(VMDK)], 600)
    if rc != 0:
        raise RuntimeError(out)


def user_data_text() -> str:
    return (SEED_SRC / "user-data").read_text(encoding="utf-8")


def build_seed_iso() -> None:
    import pycdlib

    meta = (SEED_SRC / "meta-data").read_bytes()
    user = user_data_text().encode()
    if ISO_SEED.is_file():
        ISO_SEED.unlink()
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="cidata")
    iso.add_fp(BytesIO(meta), len(meta), iso_path="/METADATA.;1", rr_name="meta-data")
    iso.add_fp(BytesIO(user), len(user), iso_path="/USERDATA.;1", rr_name="user-data")
    iso.write(str(ISO_SEED))
    iso.close()
    print(f"[reinstall] seed {ISO_SEED}")


def patch_vmx() -> None:
    text = VMX.read_text(encoding="utf-8", errors="replace")
    # 去掉 Easy Install，避免与 Subiquity 冲突
    text = re.sub(r"^guestinfo\.cis\..*\n", "", text, flags=re.M)
    ubuntu = str(ISO_UBUNTU).replace("\\", "\\\\")
    seed = str(ISO_SEED).replace("\\", "\\\\")
    text = re.sub(
        r'ide1:0\.fileName = ".*?"',
        f'ide1:0.fileName = "{ubuntu}"',
        text,
        count=1,
    )
    if "ide1:1.present" not in text:
        text += (
            f'\nide1:1.present = "TRUE"\n'
            f'ide1:1.fileName = "{seed}"\n'
            f'ide1:1.deviceType = "cdrom-image"\n'
            f'ide1:1.autodetect = "TRUE"\n'
        )
    else:
        text = re.sub(
            r'ide1:1\.fileName = ".*?"',
            f'ide1:1.fileName = "{seed}"',
            text,
            count=1,
        )
    if "bios.bootdelay" not in text:
        text += '\nbios.bootdelay = "4000"\n'
    VMX.write_text(text, encoding="utf-8")
    print("[reinstall] vmx patched (no easy-install)")


def start_vm() -> None:
    fix = ROOT / "scripts" / "local_vm" / "vmware_fix_authd.py"
    if fix.is_file():
        run([sys.executable, str(fix)], 120)
    print("[reinstall] reset + grub autoinstall...")
    run([str(VMRUN), "reset", str(VMX)], 90)
    time.sleep(4)
    grub = ROOT / "scripts" / "local_vm" / "vmware_grub_autoinstall_boot.py"
    if grub.is_file():
        run([sys.executable, str(grub)], 90)


def wait_ssh(timeout_sec: int = 3600) -> str:
    try:
        import paramiko
    except ImportError:
        print("pip install paramiko")
        return ""
    deadline = time.time() + timeout_sec
    sweep = 0
    while time.time() < deadline:
        sweep += 1
        if sweep % 3 == 1:
            print("[reinstall] polling SSH (15-45min)...", flush=True)
        for base in ("192.168.159", "192.168.233", "192.168.17"):
            for host in range(2, 254):
                ip = f"{base}.{host}"
                try:
                    c = paramiko.SSHClient()
                    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    c.connect(ip, username=VMUSER, password=VMPASS, timeout=1.2)
                    c.exec_command("echo AUTOINSTALL_OK")
                    c.close()
                    print(f"[reinstall] SSH {ip}")
                    return ip
                except Exception:
                    continue
        time.sleep(25)
    return ""


def write_env(ip: str) -> None:
    env = ROOT / "config" / "local-vm.env"
    env.write_text(
        f"VM_HOST={ip}\nVM_USER={VMUSER}\nVM_PASSWORD={VMPASS}\n"
        f"VM_SSH_PORT=22\nVM_55M_ROOT=/opt/55m-lab\nVM_BOT_ROOT=/opt/55m-lab/app\n",
        encoding="utf-8",
    )


def main() -> int:
    if not ISO_UBUNTU.is_file():
        print(f"MISSING {ISO_UBUNTU}")
        return 1
    stop_vm()
    recreate_disk()
    build_seed_iso()
    patch_vmx()
    start_vm()
    ip = wait_ssh()
    if not ip:
        print("[reinstall] FAIL: timeout — check vmware.log / installer")
        return 1
    write_env(ip)
    print(f"[reinstall] OK guest={ip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
