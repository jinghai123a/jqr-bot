#!/usr/bin/env python3
"""桌面已登录：Super 搜索 Terminal + 剪贴板粘贴装 ssh。"""
from __future__ import annotations

import subprocess
import time

VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
TITLE = "w49-edge-lab - VMware Workstation"
PASS = "w49-edge-lab"
CMD = (
    f"echo '{PASS}' | sudo -S apt-get update -qq && "
    f"echo '{PASS}' | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server && "
    "sudo systemctl enable --now ssh && hostname -I && systemctl is-active ssh"
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


def paste(pyautogui, text: str) -> None:
    import pyperclip

    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")


def main() -> int:
    import pyautogui

    pyautogui.FAILSAFE = False
    subprocess.Popen([VMWARE, VMX])
    time.sleep(2)
    cr = client()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch = cr
    pyautogui.click(sx + cw // 2, sy + ch // 2)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.6)
    pyautogui.press("win")
    time.sleep(1.2)
    paste(pyautogui, "terminal")
    time.sleep(1.0)
    pyautogui.press("enter")
    time.sleep(4)
    paste(pyautogui, CMD)
    time.sleep(0.3)
    pyautogui.press("enter")
    print("PASTE_CMD_SENT wait 150s")
    time.sleep(150)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
