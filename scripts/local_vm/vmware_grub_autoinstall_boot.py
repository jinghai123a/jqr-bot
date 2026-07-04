#!/usr/bin/env python3
"""Ubuntu Desktop ISO：GRUB 追加 autoinstall 启动参数。"""
from __future__ import annotations

import subprocess
import time

VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
TITLE = "w49-edge-lab - VMware Workstation"
# cidata 在 ide1:1 → 通常 /dev/sr1
AUTOINSTALL_ARGS = " autoinstall ds=nocloud;s=/dev/sr1/"


def client_rect():
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
    pyautogui.click(sx + cw // 2, sy + ch // 2)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.45)


def main() -> int:
    try:
        import pyautogui
    except ImportError:
        print("pip install pyautogui")
        return 1

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.04
    subprocess.Popen([VMWARE, VMX])
    time.sleep(2.5)
    cr = client_rect()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch = cr
    grab(pyautogui, sx, sy, cw, ch)
    print("[grub-ai] wait boot menu (Shift/Esc)...")
    for _ in range(50):
        pyautogui.press("shift")
        time.sleep(0.12)
        pyautogui.press("esc")
        time.sleep(0.12)
    time.sleep(1.0)
    grab(pyautogui, sx, sy, cw, ch)
    pyautogui.press("e")
    time.sleep(1.0)
    # linux 行：down 一次通常到 Install 子项或 linux 行
    pyautogui.press("down")
    time.sleep(0.2)
    pyautogui.press("end")
    time.sleep(0.15)
    pyautogui.write(AUTOINSTALL_ARGS, interval=0.02)
    time.sleep(0.25)
    pyautogui.hotkey("ctrl", "x")
    print("[grub-ai] boot autoinstall sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
