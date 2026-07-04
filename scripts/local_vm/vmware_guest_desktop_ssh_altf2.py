#!/usr/bin/env python3
"""Alt+F2 运行 gnome-terminal + 剪贴板装 ssh。"""
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
    "sudo systemctl enable --now ssh && hostname -I"
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
    import pyperclip

    pyautogui.FAILSAFE = False
    subprocess.Popen([VMWARE, VMX])
    time.sleep(2)
    cr = client()
    if not cr:
        return 1
    sx, sy, cw, ch = cr
    for _ in range(2):
        pyautogui.click(sx + cw // 2, sy + ch // 2)
        time.sleep(0.2)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.8)
    pyautogui.hotkey("alt", "f2")
    time.sleep(1.5)
    pyperclip.copy("gnome-terminal")
    pyautogui.hotkey("ctrl", "v")
    pyautogui.press("enter")
    time.sleep(5)
    pyperclip.copy(CMD)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)
    pyautogui.press("enter")
    print("ALT_F2_DONE")
    time.sleep(150)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
