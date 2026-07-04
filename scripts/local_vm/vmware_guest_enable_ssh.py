#!/usr/bin/env python3
"""Guest 重启后：开终端装 openssh-server。"""
from __future__ import annotations

import subprocess
import time

VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
TITLE = "w49-edge-lab - VMware Workstation"
PASS = "w49-edge-lab"


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
    u.SetForegroundWindow(h)
    return p.x, p.y, r.right, r.bottom


def main() -> int:
    import pyautogui

    pyautogui.FAILSAFE = False
    subprocess.Popen([VMWARE, VMX])
    time.sleep(3)
    cr = client()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch = cr
    pyautogui.click(sx + cw // 2, sy + ch // 2)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.5)
    # 登录页：输入密码回车
    pyautogui.typewrite(PASS, interval=0.05)
    pyautogui.press("enter")
    time.sleep(8)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "alt", "t")
    time.sleep(3)
    cmd = (
        f"echo '{PASS}' | sudo -S apt-get update -qq && "
        f"echo '{PASS}' | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server && "
        "sudo systemctl enable --now ssh && hostname -I"
    )
    pyautogui.typewrite(cmd, interval=0.008)
    pyautogui.press("enter")
    print("SSH_INSTALL_SENT wait 90s")
    time.sleep(90)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
