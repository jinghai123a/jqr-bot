#!/usr/bin/env python3
"""Easy Install 重装 + OOBE 勾选 OpenSSH → 等 SSH。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(r"C:\w49-edge-lab")
VMX = LAB / "w49-edge-lab.vmx"
VMDK = LAB / "w49-edge-lab.vmdk"
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
    if str(VMX) in out:
        run([str(VMRUN), "stop", str(VMX), "hard"], 120)
        time.sleep(2)


def recreate_disk() -> None:
    for p in LAB.glob("w49-edge-lab*.vmdk"):
        p.unlink(missing_ok=True)
    rc, out = run([str(VDISK), "-c", "-s", "40GB", "-a", "lsilogic", "-t", "1", str(VMDK)], 600)
    if rc != 0:
        raise RuntimeError(out)


def patch_vmx_easy() -> None:
    text = VMX.read_text(encoding="utf-8", errors="replace")
    # 去掉 autoinstall 第二光驱
    lines = []
    for ln in text.splitlines():
        if ln.startswith("ide1:1."):
            continue
        lines.append(ln)
    text = "\n".join(lines) + "\n"
    if "guestinfo.cis.username" not in text:
        text += (
            f'guestinfo.cis.domain = "local"\n'
            f'guestinfo.cis.username = "{VMUSER}"\n'
            f'guestinfo.cis.password = "{VMPASS}"\n'
            f'guestinfo.cis.password.confirm = "{VMPASS}"\n'
            f'guestinfo.cis.fullname = "W49 Edge Lab"\n'
            f'guestinfo.cis.autoinstall = "TRUE"\n'
        )
    VMX.write_text(text, encoding="utf-8")


def wait_ssh(timeout_sec: int = 3600) -> str:
    import paramiko

    deadline = time.time() + timeout_sec
    n = 0
    while time.time() < deadline:
        n += 1
        if n % 4 == 1:
            print("[easy] polling SSH...", flush=True)
        for base in ("192.168.159", "192.168.233"):
            for host in range(2, 254):
                ip = f"{base}.{host}"
                try:
                    c = paramiko.SSHClient()
                    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    c.connect(ip, username=VMUSER, password=VMPASS, timeout=1.0)
                    c.close()
                    print(f"[easy] SSH {ip}")
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
    fix = ROOT / "scripts" / "local_vm" / "vmware_fix_authd.py"
    if fix.is_file():
        run([sys.executable, str(fix)], 120)
    stop_vm()
    recreate_disk()
    patch_vmx_easy()
    print("[easy] start VM gui...")
    run([str(VMRUN), "start", str(VMX)], 120)
    time.sleep(8)
    oobe = ROOT / "scripts" / "local_vm" / "vmware_guest_ubuntu_oobe.py"
    if oobe.is_file():
        print("[easy] OOBE automation (openssh checkbox)...")
        subprocess.Popen([sys.executable, str(oobe)])
    ip = wait_ssh()
    if not ip:
        print("[easy] FAIL timeout")
        return 1
    write_env(ip)
    print("[easy] OK", ip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
