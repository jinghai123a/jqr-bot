#!/usr/bin/env python3
"""VMware 新建虚拟机向导 — 自动填轻松安装字段并点下一步。"""
from __future__ import annotations

import sys
import time

try:
    import pyautogui
    import pygetwindow as gw
except ImportError:
    print("pip install pyautogui pygetwindow")
    raise SystemExit(1)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.35

FULL = "W49 Edge Lab"
USER = "bot"
PASS = "w49-edge-lab"


def find_wizard():
    keys = (
        "New Virtual Machine",
        "新建虚拟机",
        "Virtual Machine Wizard",
        "Easy Install",
        "轻松安装",
        "w49-edge-lab",
    )
    wins = gw.getAllWindows()
    for w in wins:
        t = (w.title or "").strip()
        if not t:
            continue
        if any(k.lower() in t.lower() for k in keys):
            return w
    return None


def focus(w) -> None:
    try:
        if w.isMinimized:
            w.restore()
        w.activate()
    except Exception:
        pass
    time.sleep(0.8)


def fill_easy_install() -> None:
    w = find_wizard()
    if w:
        focus(w)
        print("window:", w.title)
    else:
        print("WARN: wizard window not found — focus VMware manually 3s")
        time.sleep(3)
    # 全名 → 用户名 → 密码 → 确认 → 下一步
    pyautogui.hotkey("alt", "f")  # 全名快捷键 (F) 部分向导支持
    time.sleep(0.2)
    pyautogui.click()  # 确保焦点在窗内
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(FULL, interval=0.03)
    pyautogui.press("tab")
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(USER, interval=0.03)
    pyautogui.press("tab")
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(PASS, interval=0.03)
    pyautogui.press("tab")
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(PASS, interval=0.03)
    time.sleep(0.3)
    pyautogui.hotkey("alt", "n")  # 下一步
    print("EASY_INSTALL_FILLED")


def main() -> int:
    print("3s 后自动填表 — 鼠标移到左上角可中止")
    time.sleep(3)
    fill_easy_install()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
