#!/usr/bin/env python3
"""GRUB init=/bin/bash → 根 shell 装 openssh-server。"""
from __future__ import annotations

import subprocess
import sys
import time

VMRUN = r"C:\Users\haijin\VMware\Installation\vmrun.exe"
VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
TITLE = "w49-edge-lab - VMware Workstation"
PASS = "w49-edge-lab"
VM_HOST = "192.168.159.130"
VM_USER = "bot"


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "timeout"


def client_rect():
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    h = u.FindWindowW(None, TITLE)
    if not h:
        return None
    r = wintypes.RECT()
    u.GetClientRect(h, ctypes.byref(r))
    p = wintypes.POINT(0, 0)
    u.ClientToScreen(h, ctypes.byref(p))
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    return p.x, p.y, r.right, r.bottom


def grab(pyautogui, sx, sy, cw, ch) -> None:
    pyautogui.click(sx + cw // 2, sy + ch // 2)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.4)


def send_line(pyautogui, line: str, delay: float = 1.0) -> None:
    pyautogui.write(line, interval=0.015)
    pyautogui.press("enter")
    time.sleep(delay)


def wait_ssh(timeout_sec: int = 300) -> bool:
    try:
        import paramiko
    except ImportError:
        return False
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(VM_HOST, username=VM_USER, password=PASS, timeout=8)
            c.exec_command("echo GRUB_SSH_OK")
            c.close()
            print("[grub] SSH OK")
            return True
        except Exception:
            time.sleep(8)
    return False


def main() -> int:
    try:
        import pyautogui
    except ImportError:
        print("pip install pyautogui")
        return 1

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.03
    print("[grub] reset VM...")
    run([VMRUN, "reset", VMX], 90)
    subprocess.Popen([VMWARE, VMX])
    time.sleep(3)
    cr = client_rect()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch = cr
    grab(pyautogui, sx, sy, cw, ch)
    print("[grub] spam Shift/Esc for GRUB...")
    for _ in range(40):
        pyautogui.press("shift")
        time.sleep(0.15)
        pyautogui.press("esc")
        time.sleep(0.15)
    time.sleep(1.5)
    grab(pyautogui, sx, sy, cw, ch)
    pyautogui.press("e")
    time.sleep(1.2)
    # 到 linux 行：通常第二段；多按几次 down 再 end 追加
    for _ in range(2):
        pyautogui.press("down")
        time.sleep(0.15)
    pyautogui.press("end")
    time.sleep(0.2)
    pyautogui.write(" init=/bin/bash", interval=0.02)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "x")
    print("[grub] booting init=/bin/bash ...")
    time.sleep(12)
    grab(pyautogui, sx, sy, cw, ch)
    cmds = [
        "mount -o remount,rw /",
        "apt-get update -qq",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server open-vm-tools open-vm-tools-desktop",
        "systemctl enable --now ssh",
        "sync",
        "reboot -f",
    ]
    for cmd in cmds:
        print(f"[grub] {cmd[:50]}")
        send_line(pyautogui, cmd, delay=50.0 if "apt-get install" in cmd else 6.0)
    print("[grub] wait SSH after reboot...")
    if wait_ssh(420):
        return 0
    print("[grub] FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
