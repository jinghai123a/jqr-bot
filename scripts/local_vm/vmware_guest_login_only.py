#!/usr/bin/env python3
"""GDM 登录 — 多坐标轮询 + 剪贴板粘贴密码。"""
from __future__ import annotations

import subprocess
import time

VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
TITLE = "w49-edge-lab - VMware Workstation"
PASS = "w49-edge-lab"

# 相对客户区，密码框可能位置
POINTS = [(0.50, 0.52), (0.50, 0.56), (0.50, 0.60), (0.50, 0.64), (0.48, 0.58)]


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
    try:
        import pyperclip

        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pyautogui.write(text, interval=0.1)


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
    for i, (rx, ry) in enumerate(POINTS):
        x = sx + int(cw * rx)
        y = sy + int(ch * ry)
        pyautogui.click(x, y, clicks=3, interval=0.1)
        time.sleep(0.25)
        pyautogui.hotkey("ctrl", "a")
        paste(pyautogui, PASS)
        time.sleep(0.2)
        pyautogui.press("enter")
        print(f"try {i + 1} at {rx},{ry}")
        time.sleep(4)
    print("DONE password=w49-edge-lab")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
