#!/usr/bin/env python3
"""终端已开：不重启 VM，聚焦后 typewrite。"""
from __future__ import annotations

import time

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
    pyautogui.PAUSE = 0.03
    cr = client()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch = cr
    tx, ty = sx + cw // 2, sy + int(ch * 0.52)
    for _ in range(3):
        pyautogui.click(tx, ty)
        time.sleep(0.25)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(1.0)
    pyautogui.hotkey("ctrl", "u")
    time.sleep(0.2)
    pyautogui.write(CMD, interval=0.012)
    pyautogui.press("enter")
    print("SENT")
    time.sleep(180)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
