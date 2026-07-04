#!/usr/bin/env python3
"""Ubuntu 账户页 — Win32 前台 + 客户区坐标填表。"""
from __future__ import annotations

import subprocess
import sys
import time

VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
TITLE = "w49-edge-lab"

# 相对 VMware 客户区 (0..1)：Ubuntu 安装器右侧五个输入框
FIELDS = [
    (0.72, 0.42, "W49 Edge Lab"),
    (0.72, 0.50, "w49-edge-lab"),
    (0.72, 0.58, "bot"),
    (0.72, 0.66, "w49-edge-lab"),
    (0.72, 0.74, "w49-edge-lab"),
]
NEXT_BTN = (0.92, 0.93)


def client_rect():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, f"{TITLE} - VMware Workstation")
    if not hwnd:
        for t in (f"{TITLE} - VMware Workstation", "VMware Workstation"):
            hwnd = user32.FindWindowW(None, t)
            if hwnd:
                break
    if not hwnd:
        return None
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    user32.SetForegroundWindow(hwnd)
    return pt.x, pt.y, rect.right, rect.bottom, hwnd


def main() -> int:
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.08
    subprocess.Popen([VMWARE, VMX])
    time.sleep(3)
    cr = client_rect()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch, _hwnd = cr
    print(f"client {cw}x{ch} at ({sx},{sy})")
    # 点进 MKS 区域中心抢焦点
    mx = sx + cw // 2
    my = sy + ch // 2
    pyautogui.click(mx, my)
    time.sleep(0.4)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.5)
    for rx, ry, text in FIELDS:
        x = sx + int(cw * rx)
        y = sy + int(ch * ry)
        pyautogui.click(x, y, clicks=3)
        time.sleep(0.25)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        # 纯 ASCII 密码用 typewrite；含空格用 write
        pyautogui.write(text, interval=0.05)
        print("ok:", text)
        time.sleep(0.35)
    nx = sx + int(cw * NEXT_BTN[0])
    ny = sy + int(ch * NEXT_BTN[1])
    time.sleep(0.5)
    pyautogui.click(nx, ny)
    print("NEXT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
