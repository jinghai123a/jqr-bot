#!/usr/bin/env python3
"""关闭 Ubuntu Software Updater 弹窗。"""
from __future__ import annotations

import time

TITLE = "w49-edge-lab - VMware Workstation"
# 「稍后提醒我」约在弹窗右下
REMIND_LATER = (0.62, 0.62)


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
    cr = client()
    if not cr:
        return 1
    sx, sy, cw, ch = cr
    pyautogui.click(sx + cw // 2, sy + ch // 2)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.5)
    pyautogui.click(sx + int(cw * REMIND_LATER[0]), sy + int(ch * REMIND_LATER[1]))
    print("DISMISS_UPDATER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
