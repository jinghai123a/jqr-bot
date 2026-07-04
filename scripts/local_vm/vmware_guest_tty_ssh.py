#!/usr/bin/env python3
"""黑屏/无桌面时：TTY2 登录 → openssh-server + open-vm-tools。"""
from __future__ import annotations

import subprocess
import sys
import time

VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
TITLE = "w49-edge-lab - VMware Workstation"
USER = "bot"
PASS = "w49-edge-lab"


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


def paste(pyautogui, text: str) -> None:
    try:
        import pyperclip

        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pyautogui.write(text, interval=0.06)


def grab_guest(pyautogui, sx: int, sy: int, cw: int, ch: int) -> None:
    pyautogui.click(sx + cw // 2, sy + ch // 2)
    time.sleep(0.25)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.5)


def send_line(pyautogui, line: str, *, delay: float = 0.35) -> None:
    paste(pyautogui, line)
    time.sleep(0.1)
    pyautogui.press("enter")
    time.sleep(delay)


def main() -> int:
    try:
        import pyautogui
    except ImportError:
        print("pip install pyautogui pyperclip")
        return 1

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.05
    subprocess.Popen([VMWARE, VMX])
    time.sleep(2.5)
    cr = client_rect()
    if not cr:
        print("NO_HWND")
        return 1
    sx, sy, cw, ch = cr
    grab_guest(pyautogui, sx, sy, cw, ch)
    # 退出可能卡住的图形会话，进 TTY2
    pyautogui.hotkey("ctrl", "alt", "f2")
    time.sleep(2.5)
    grab_guest(pyautogui, sx, sy, cw, ch)
    send_line(pyautogui, USER, delay=1.0)
    send_line(pyautogui, PASS, delay=2.0)
    cmds = [
        f"echo '{PASS}' | sudo -S apt-get update -qq",
        f"echo '{PASS}' | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server open-vm-tools open-vm-tools-desktop",
        f"echo '{PASS}' | sudo -S systemctl enable --now ssh",
        "hostname -I && systemctl is-active ssh",
    ]
    for cmd in cmds:
        print(f"RUN {cmd[:60]}...")
        send_line(pyautogui, cmd, delay=45.0 if "apt-get install" in cmd else 8.0)
    print("TTY_SSH_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
