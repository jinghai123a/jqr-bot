#!/usr/bin/env python3
"""Ubuntu 安装/OOBE — 连点「下一步」直到进桌面。"""
from __future__ import annotations

import subprocess
import time

VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
USER = "bot"
PASS = "w49-edge-lab"


def get_vm_win(gw):
    for w in gw.getAllWindows():
        t = w.title or ""
        if "w49-edge" in t.lower() and "workstation" in t.lower():
            return w
    return None


def focus(pyautogui, gw):
    subprocess.Popen([VMWARE, VMX])
    time.sleep(2)
    w = get_vm_win(gw)
    if not w:
        return None
    try:
        w.maximize()
    except Exception:
        pass
    try:
        w.activate()
    except Exception:
        pass
    pyautogui.click(w.left + w.width // 2, w.top + w.height // 2)
    time.sleep(0.25)
    pyautogui.hotkey("ctrl", "g")
    return w


def click_bottom_right(pyautogui, w, dx=110, dy=78):
    pyautogui.click(w.left + w.width - dx, w.top + w.height - dy)


def dismiss_tools(pyautogui, w):
    pyautogui.click(w.left + int(w.width * 0.82), w.top + w.height - 48)
    time.sleep(0.4)


def fill_user_if_needed(pyautogui):
    pyautogui.write("W49 Edge Lab", interval=0.02)
    pyautogui.press("tab")
    pyautogui.write("w49-edge-lab", interval=0.02)
    pyautogui.press("tab")
    pyautogui.write(USER, interval=0.02)
    pyautogui.press("tab")
    pyautogui.write(PASS, interval=0.02)
    pyautogui.press("tab")
    pyautogui.write(PASS, interval=0.02)


def main() -> int:
    import pyautogui
    import pygetwindow as gw

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.15
    w = focus(pyautogui, gw)
    if not w:
        print("NO_VM")
        return 1
    dismiss_tools(pyautogui, w)
    for i in range(2):
        click_bottom_right(pyautogui, w)
        time.sleep(2.0)
        print(f"next {i + 1}")
        w = get_vm_win(gw) or w
    pyautogui.press("tab")
    time.sleep(0.2)
    pyautogui.press("tab")
    time.sleep(0.2)
    pyautogui.press("space")
    time.sleep(0.3)
    print("openssh_checked")
    for i in range(6):
        click_bottom_right(pyautogui, w)
        time.sleep(2.0)
        print(f"next {i + 3}")
        w = get_vm_win(gw) or w
    fill_user_if_needed(pyautogui)
    time.sleep(0.5)
    click_bottom_right(pyautogui, w)
    print("user_submit")
    # 安装进度 + 重启
    for i in range(60):
        time.sleep(30)
        w = focus(pyautogui, gw)
        if not w:
            continue
        click_bottom_right(pyautogui, w, dx=130, dy=70)
        print(f"wait {i + 1}/60 click restart/next")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
