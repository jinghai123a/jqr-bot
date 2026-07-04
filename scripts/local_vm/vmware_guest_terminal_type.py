#!/usr/bin/env python3
"""终端已开：typewrite 装 openssh（无 Tools 不用剪贴板）。"""
from __future__ import annotations

import subprocess
import time

VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
TITLE = "w49-edge-lab - VMware Workstation"
CMD = (
    "echo w49-edge-lab | sudo -S apt install -y openssh-server && "
    "sudo systemctl enable --now ssh"
)


def client():
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


def main() -> int:
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.02
    subprocess.Popen([VMWARE, VMX])
    time.sleep(1.5)
    cr = client()
    if not cr:
        return 1
    sx, sy, cw, ch = cr
    pyautogui.click(sx + cw // 2, sy + int(ch * 0.55))
    time.sleep(0.4)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.6)
    pyautogui.hotkey("ctrl", "u")
    time.sleep(0.15)
    pyautogui.write(CMD, interval=0.015)
    time.sleep(0.2)
    pyautogui.press("enter")
    print("TYPEWRITE_SENT")
    time.sleep(150)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
