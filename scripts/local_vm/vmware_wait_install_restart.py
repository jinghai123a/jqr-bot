#!/usr/bin/env python3
"""等「Setting up the system」结束 → 点 Restart → 等 SSH。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
TITLE = "w49-edge-lab - VMware Workstation"
RESTART = (0.88, 0.90)


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
    u.SetForegroundWindow(h)
    return p.x, p.y, r.right, r.bottom


def click_restart(pyautogui, sx, sy, cw, ch) -> None:
    pyautogui.click(sx + cw // 2, sy + ch // 2)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "g")
    time.sleep(0.3)
    pyautogui.click(sx + int(cw * RESTART[0]), sy + int(ch * RESTART[1]))


def wait_ssh(timeout_sec: int = 900) -> bool:
    import paramiko

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect("192.168.159.130", username="bot", password="w49-edge-lab", timeout=5)
            c.close()
            return True
        except Exception:
            time.sleep(15)
    return False


def main() -> int:
    import pyautogui

    pyautogui.FAILSAFE = False
    subprocess.Popen([VMWARE, VMX])
    time.sleep(2)
    print("[wait] click Restart every 90s until SSH up...")
    for i in range(80):
        cr = client()
        if cr:
            click_restart(pyautogui, *cr)
            print(f"[wait] restart click {i + 1}")
        if wait_ssh(timeout_sec=90):
            print("[wait] SSH_OK")
            return 0
        time.sleep(90)
    print("[wait] FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
