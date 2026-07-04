#!/usr/bin/env python3
"""VMware GUI 一键开机 + 轻松安装填表。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

VMX = Path(r"C:\w49-edge-lab\w49-edge-lab.vmx")
VMWARE = Path(r"C:\Users\haijin\VMware\Installation\vmware.exe")
VMRUN = Path(r"C:\Users\haijin\VMware\Installation\vmrun.exe")
USER = "bot"
PASS = "w49-edge-lab"
FULL = "W49 Edge Lab"


def vm_running() -> bool:
    if not VMRUN.is_file():
        return False
    r = subprocess.run([str(VMRUN), "list"], capture_output=True, text=True, timeout=30)
    return str(VMX).lower() in (r.stdout or "").lower()


def gui_power_on() -> None:
    try:
        import pyautogui
        import pygetwindow as gw
    except ImportError:
        print("pip install pyautogui pygetwindow")
        return
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.25

    subprocess.Popen([str(VMWARE), str(VMX)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)

    for _ in range(30):
        wins = [
            w
            for w in gw.getAllWindows()
            if w.title and ("w49-edge" in w.title.lower() or "edge lab" in w.title.lower())
        ]
        if wins:
            w = wins[0]
            try:
                if w.isMinimized:
                    w.restore()
                w.activate()
            except Exception:
                pass
            time.sleep(0.8)
            cx = w.left + max(80, w.width // 8)
            cy = w.top + max(60, w.height // 6)
            pyautogui.click(cx, cy)
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "b")
            pyautogui.hotkey("ctrl", "alt", "p")
            break
        time.sleep(1)

    time.sleep(2)
    for w in gw.getAllWindows():
        t = w.title or ""
        if any(k in t for k in ("Easy Install", "轻松安装", "New Virtual Machine", "新建虚拟机")):
            try:
                w.activate()
            except Exception:
                pass
            time.sleep(0.5)
            pyautogui.typewrite(FULL, interval=0.02)
            pyautogui.press("tab")
            pyautogui.typewrite(USER, interval=0.02)
            pyautogui.press("tab")
            pyautogui.typewrite(PASS, interval=0.02)
            pyautogui.press("tab")
            pyautogui.typewrite(PASS, interval=0.02)
            pyautogui.hotkey("alt", "n")
            print("EASY_INSTALL_FILLED")
            break


def main() -> int:
    if vm_running():
        print("VM_ALREADY_RUNNING")
        return 0
    fix = Path(__file__).resolve().parent / "vmware_fix_authd.py"
    subprocess.run([sys.executable, str(fix)], timeout=120)
    if VMRUN.is_file():
        r = subprocess.run([str(VMRUN), "start", str(VMX), "nogui"], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            print("VMRUN_START_OK")
            return 0
        print("vmrun:", (r.stderr or r.stdout or "")[:200])
    gui_power_on()
    for _ in range(24):
        if vm_running():
            print("VM_GUI_START_OK")
            return 0
        time.sleep(5)
    print("VM_START_PENDING")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
