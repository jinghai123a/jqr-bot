#!/usr/bin/env python3
"""终端已开：分步 sudo（避免管道符键盘布局问题）。"""
from __future__ import annotations

import time

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
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    return p.x, p.y, r.right, r.bottom


def grab(pyautogui, sx, sy, cw, ch) -> None:
    pyautogui.click(sx + cw // 2, sy + int(ch * 0.52))
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.8)


def line(pyautogui, text: str, delay: float = 2.0) -> None:
    pyautogui.hotkey("ctrl", "u")
    time.sleep(0.1)
    pyautogui.write(text, interval=0.02)
    pyautogui.press("enter")
    time.sleep(delay)


def main() -> int:
    import pyautogui

    pyautogui.FAILSAFE = False
    cr = client()
    if not cr:
        return 1
    grab(pyautogui, *cr)
    line(pyautogui, "sudo apt update", 8.0)
    grab(pyautogui, *cr)
    line(pyautogui, PASS, 3.0)
    grab(pyautogui, *cr)
    line(pyautogui, "sudo apt install -y openssh-server", 5.0)
    grab(pyautogui, *cr)
    line(pyautogui, PASS, 3.0)
    grab(pyautogui, *cr)
    line(pyautogui, "sudo systemctl enable --now ssh", 5.0)
    grab(pyautogui, *cr)
    line(pyautogui, PASS, 3.0)
    grab(pyautogui, *cr)
    line(pyautogui, "systemctl is-active ssh", 2.0)
    print("STEPWISE_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
