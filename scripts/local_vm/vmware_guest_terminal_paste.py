#!/usr/bin/env python3
"""终端已开：清屏 + 剪贴板粘贴装 openssh。"""
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
    "sudo systemctl enable --now ssh && ss -tlnp | grep :22 && hostname -I"
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
    time.sleep(1.5)
    cr = client()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch = cr
    # 点终端区域（客户区中部）
    pyautogui.click(sx + cw // 2, sy + ch // 2)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.1)
    pyautogui.press("backspace")
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "u")
    time.sleep(0.2)
    pyperclip.copy(CMD)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    pyautogui.press("enter")
    print("CMD_SENT")
    time.sleep(120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
