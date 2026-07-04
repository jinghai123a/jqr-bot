#!/usr/bin/env python3
"""Ubuntu 24.04 Desktop 安装向导 — 自动点 Next + 填 bot 账户。"""
from __future__ import annotations

import subprocess
import time

VMX = r"C:\w49-edge-lab\w49-edge-lab.vmx"
VMWARE = r"C:\Users\haijin\VMware\Installation\vmware.exe"
USER = "bot"
PASS = "w49-edge-lab"
FULL = "W49 Edge Lab"
HOST = "w49-edge-lab"


def focus_guest(pyautogui, gw):
    subprocess.Popen([VMWARE, VMX])
    time.sleep(3)
    for w in gw.getAllWindows():
        t = w.title or ""
        if "w49-edge" in t.lower() and "workstation" in t.lower():
            try:
                w.maximize()
            except Exception:
                pass
            try:
                w.activate()
            except Exception:
                pass
            pyautogui.click(w.left + w.width // 2, w.top + w.height // 2)
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "g")
            return w
    return None


def dismiss_tools_bar(pyautogui, w) -> None:
    # 底部黄条「不要提醒我」约在窗口下方
    x = w.left + int(w.width * 0.72)
    y = w.top + w.height - 55
    pyautogui.click(x, y)
    time.sleep(0.5)


def click_next(pyautogui, w) -> None:
    x = w.left + w.width - 120
    y = w.top + w.height - 80
    pyautogui.click(x, y)
    time.sleep(1.2)


def fill_user_form(pyautogui) -> None:
    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(FULL, interval=0.02)
    pyautogui.press("tab")
    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(HOST, interval=0.02)
    pyautogui.press("tab")
    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(USER, interval=0.02)
    pyautogui.press("tab")
    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(PASS, interval=0.02)
    pyautogui.press("tab")
    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(PASS, interval=0.02)


def main() -> int:
    import pyautogui
    import pygetwindow as gw

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.2
    w = focus_guest(pyautogui, gw)
    if not w:
        print("NO_VM")
        return 1
    dismiss_tools_bar(pyautogui, w)
    # 语言页 → 键盘 → 软件 → 磁盘 → 时区 → 用户
    for step in range(5):
        click_next(pyautogui, w)
        print(f"next {step + 1}")
    fill_user_form(pyautogui)
    time.sleep(0.5)
    click_next(pyautogui, w)
    print("USER_FORM_DONE waiting install...")
    # 安装完成后会出现 Restart — 多轮点 Next/Restart
    for _ in range(40):
        time.sleep(60)
        w2 = focus_guest(pyautogui, gw)
        if not w2:
            continue
        click_next(pyautogui, w2)
        # Restart Now 按钮偏右下
        pyautogui.click(w2.left + w2.width - 140, w2.top + w2.height - 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
