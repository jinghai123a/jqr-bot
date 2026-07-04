#!/usr/bin/env python3
"""UAC 循环点「是」并启动 VMAuthdService。"""
from __future__ import annotations

import subprocess
import sys
import time


def service_status() -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "(Get-Service VMAuthdService).Status"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return (r.stdout or "").strip()


def main() -> int:
    try:
        import pyautogui
        import pygetwindow as gw
    except ImportError:
        print("pip install pyautogui pygetwindow")
        return 1

    pyautogui.FAILSAFE = False
    if service_status() == "Running":
        print("AUTHD_OK")
        return 0

    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Start-Process powershell -Verb RunAs -ArgumentList "
            "'-NoProfile','-Command','Start-Service VMAuthdService'",
        ]
    )
    print("UAC loop 60s...")
    for _ in range(60):
        for w in gw.getAllWindows():
            t = w.title or ""
            if any(x in t for x in ("Account Control", "账户控制", "用户账户")):
                try:
                    w.activate()
                except Exception:
                    pass
                print("UAC:", t)
        pyautogui.press("left")
        pyautogui.press("enter")
        pyautogui.hotkey("alt", "y")
        if service_status() == "Running":
            print("AUTHD_OK")
            return 0
        time.sleep(1)
    print("AUTHD_FAIL", service_status())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
