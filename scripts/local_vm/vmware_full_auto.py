#!/usr/bin/env python3
"""VMware 全自动：建盘→开机→装系统→等 IP→部署→测试。零人工。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(r"C:\w49-edge-lab")
VMX = LAB / "w49-edge-lab.vmx"
VMDK = LAB / "w49-edge-lab.vmdk"
ISO = Path(r"D:\ISO\ubuntu-24.04.4-desktop-amd64.iso")
VMRUN = Path(r"C:\Users\haijin\VMware\Installation\vmrun.exe")
VDISK = Path(r"C:\Users\haijin\VMware\Installation\vmware-vdiskmanager.exe")
VMUSER = "bot"
VMPASS = "w49-edge-lab"


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return -1, "timeout"


def ensure_disk() -> None:
    if VMDK.is_file():
        return
    print("[auto] create vmdk 40GB...")
    rc, out = run([str(VDISK), "-c", "-s", "40GB", "-a", "lsilogic", "-t", "1", str(VMDK)], 600)
    if rc != 0:
        raise RuntimeError(f"vmdk failed: {out}")


def ensure_vmx() -> None:
    if not VMX.is_file():
        raise RuntimeError(f"missing {VMX}")
    text = VMX.read_text(encoding="utf-8", errors="replace")
    if str(ISO).replace("\\", "\\\\") not in text:
        text = re.sub(
            r'ide1:0\.fileName = ".*?"',
            f'ide1:0.fileName = "{ISO.as_posix().replace(chr(92), chr(92)*2)}"',
            text,
            count=1,
        )
    for k, v in [
        ("guestinfo.cis.username", VMUSER),
        ("guestinfo.cis.password", VMPASS),
        ("guestinfo.cis.password.confirm", VMPASS),
        ("guestinfo.cis.fullname", "W49 Edge Lab"),
        ("guestinfo.cis.autoinstall", "TRUE"),
    ]:
        line = f'guestinfo.cis.{k.split(".")[-1]} = "{v}"' if "fullname" not in k else f'guestinfo.cis.fullname = "{v}"'
        if k == "guestinfo.cis.username":
            line = f'guestinfo.cis.username = "{v}"'
        elif k == "guestinfo.cis.password":
            line = f'guestinfo.cis.password = "{v}"'
        elif k == "guestinfo.cis.password.confirm":
            line = f'guestinfo.cis.password.confirm = "{v}"'
        elif k == "guestinfo.cis.autoinstall":
            line = f'guestinfo.cis.autoinstall = "{v}"'
        if k not in text and "guestinfo" in k:
            pass
    if "guestinfo.cis.username" not in text:
        text += f'\nguestinfo.cis.domain = "local"\n'
        text += f'guestinfo.cis.username = "{VMUSER}"\n'
        text += f'guestinfo.cis.password = "{VMPASS}"\n'
        text += f'guestinfo.cis.password.confirm = "{VMPASS}"\n'
        text += f'guestinfo.cis.fullname = "W49 Edge Lab"\n'
        text += f'guestinfo.cis.autoinstall = "TRUE"\n'
    VMX.write_text(text, encoding="utf-8")


def vm_list() -> list[str]:
    rc, out = run([str(VMRUN), "list"])
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().endswith(".vmx")]
    return lines


def ensure_vmware_path() -> None:
    """Registry 指向 C:\\VMware\\Installation，实际装在用户目录时用 junction。"""
    dst = Path(r"C:\VMware\Installation")
    src = Path(r"C:\Users\haijin\VMware\Installation")
    if dst.exists() or not src.is_dir():
        return
    Path(r"C:\VMware").mkdir(parents=True, exist_ok=True)
    run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], 30)


def ensure_authd() -> None:
    fix = ROOT / "scripts" / "local_vm" / "vmware_fix_authd.py"
    if fix.is_file():
        run([sys.executable, str(fix)], 150)


def vm_start() -> None:
    if any(str(VMX).lower() in x.lower() for x in vm_list()):
        print("[auto] VM already running")
        return
    print("[auto] vmrun start (nogui)...")
    rc, out = run([str(VMRUN), "start", str(VMX), "nogui"], 120)
    if rc != 0 and "already running" not in out.lower():
        print("[auto] nogui fail, try gui:", out[:200])
        run([sys.executable, str(ROOT / "scripts" / "local_vm" / "vmware_gui_poweron.py")], 180)


def vm_ip(timeout_sec: int = 2400) -> str:
    deadline = time.time() + timeout_sec
    sweep = 0
    while time.time() < deadline:
        rc, out = run(
            [str(VMRUN), "-T", "ws", "getGuestIPAddress", str(VMX)],
            20,
        )
        for line in out.splitlines():
            line = line.strip()
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", line):
                print(f"[auto] vmrun IP {line}")
                return line
        try:
            import paramiko

            sweep += 1
            if sweep % 3 == 0:
                print("[auto] ssh sweep...", flush=True)
            for base in ("192.168.159", "192.168.233", "192.168.17", "192.168.56"):
                for host in range(2, 254):
                    ip = f"{base}.{host}"
                    try:
                        c = paramiko.SSHClient()
                        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        c.connect(ip, username=VMUSER, password=VMPASS, timeout=0.8)
                        c.close()
                        print(f"[auto] ssh IP {ip}")
                        return ip
                    except Exception:
                        continue
        except ImportError:
            pass
        print("[auto] waiting install/ssh...", flush=True)
        time.sleep(20)
    return ""


def wizard_click_through() -> None:
    """仅在新建虚拟机向导窗口时填表，避免误触已打开的设置页。"""
    try:
        import pygetwindow as gw
    except ImportError:
        return
    keys = ("new virtual machine", "新建虚拟机", "virtual machine wizard", "虚拟机向导")
    wins = [
        w for w in gw.getAllWindows()
        if w.title and any(k in w.title.lower() for k in keys)
    ]
    if not wins:
        return
    try:
        import pyautogui
    except ImportError:
        return
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.25
    w = wins[0]
    try:
        w.activate()
    except Exception:
        pass
    time.sleep(0.5)
    pyautogui.typewrite("W49 Edge Lab", interval=0.02)
    pyautogui.press("tab")
    pyautogui.typewrite(VMUSER, interval=0.02)
    pyautogui.press("tab")
    pyautogui.typewrite(VMPASS, interval=0.02)
    pyautogui.press("tab")
    pyautogui.typewrite(VMPASS, interval=0.02)
    pyautogui.hotkey("alt", "n")
    print("[auto] wizard filled")


def write_local_vm_env(ip: str) -> None:
    env = ROOT / "config" / "local-vm.env"
    example = ROOT / "config" / "local-vm.env.example"
    lines: list[str] = []
    if example.is_file():
        lines = example.read_text(encoding="utf-8").splitlines()
    data = {k.strip(): v.strip() for ln in lines if "=" in ln and not ln.strip().startswith("#")
            for k, v in [ln.split("=", 1)]}
    data["VM_HOST"] = ip
    data["VM_USER"] = VMUSER
    data["VM_PASSWORD"] = VMPASS
    data["VM_55M_ROOT"] = "/opt/55m-lab"
    data["VM_BOT_ROOT"] = "/opt/55m-lab/app"
    out = [f"{k}={v}" for k, v in data.items()]
    env.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[auto] wrote {env}")


def deploy_and_test() -> int:
    rc, out = run([sys.executable, str(ROOT / "scripts" / "local_vm" / "host_deploy.py"), "--all"], 1800)
    print(out[-3000:] if len(out) > 3000 else out)
    if rc != 0:
        return rc
    rc2, out2 = run([sys.executable, str(ROOT / "scripts" / "local_vm" / "host_test_suite.py")], 300)
    print(out2[-2000:])
    return rc2


def main() -> int:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    wizard_click_through()
    ensure_disk()
    ensure_vmx()
    ensure_vmware_path()
    ensure_authd()
    vm_start()
    print("[auto] Ubuntu installing 15-40min — polling IP/SSH...")
    ip = vm_ip(timeout_sec=2400)
    if not ip:
        print("[auto] FAIL: no guest IP — VM still installing; re-run later")
        return 1
    write_local_vm_env(ip)
    return deploy_and_test()


if __name__ == "__main__":
    raise SystemExit(main())
