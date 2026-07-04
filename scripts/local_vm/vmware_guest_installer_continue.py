#!/usr/bin/env python3
"""Ubuntu 安装向导 — Win32 客户区坐标连点 + 账户补填。"""
from __future__ import annotations

import subprocess
import time

VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
TITLE = "w49-edge-lab - VMware Workstation"

NEXT = (0.91, 0.905)
FIELDS = [
    (0.72, 0.42, "W49 Edge Lab"),
    (0.72, 0.50, "w49-edge-lab"),
    (0.72, 0.58, "bot"),
    (0.72, 0.66, "w49-edge-lab"),
    (0.72, 0.72, "w49-edge-lab"),
]


def hwnd_client():
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


def click_rel(pyautogui, sx, sy, cw, ch, rx, ry):
    pyautogui.click(sx + int(cw * rx), sy + int(ch * ry))


def main() -> int:
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.1
    subprocess.Popen([VMWARE, VMX.replace("w49-edge-lab.vmx", "w49-edge-lab.vmx")])
    time.sleep(2)
    cr = hwnd_client()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch = cr
    click_rel(pyautogui, sx, sy, cw, ch, 0.5, 0.5)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.5)
    # 时区页 -> 下一步 x3（账户/确认/安装）
    for i in range(3):
        click_rel(pyautogui, sx, sy, cw, ch, *NEXT)
        print(f"next {i + 1}")
        time.sleep(2.5)
    # 账户页补填
    for rx, ry, text in FIELDS:
        click_rel(pyautogui, sx, sy, cw, ch, rx, ry)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        pyautogui.typewrite(text, interval=0.05)
        print("field:", text)
        time.sleep(0.3)
    time.sleep(0.5)
    click_rel(pyautogui, sx, sy, cw, ch, *NEXT)
    print("ACCOUNT_NEXT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
