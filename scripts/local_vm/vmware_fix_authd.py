#!/usr/bin/env python3
"""启动 VMware Authorization Service（UAC 自动点「是」）。"""
from __future__ import annotations

import subprocess
import sys
import time


def authd_running() -> bool:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "(Get-Service VMAuthdService).Status"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return "Running" in (r.stdout or "")


def click_uac_yes() -> None:
    try:
        import pyautogui
    except ImportError:
        return
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.2
    for _ in range(8):
        time.sleep(0.8)
        try:
            import pygetwindow as gw

            for w in gw.getAllWindows():
                t = (w.title or "").lower()
                if "user account control" in t or "用户账户控制" in (w.title or ""):
                    w.activate()
                    time.sleep(0.3)
                    break
        except Exception:
            pass
        pyautogui.press("left")
        time.sleep(0.1)
        pyautogui.press("enter")
        pyautogui.hotkey("alt", "y")


def ensure_junction() -> None:
    src = r"C:\Users\haijin\VMware\Installation"
    dst = r"C:\VMware\Installation"
    if not __import__("pathlib").Path(dst).exists():
        subprocess.run(
            ["cmd", "/c", "mkdir", r"C:\VMware"],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", dst, src],
            check=False,
            capture_output=True,
        )


def main() -> int:
    ensure_junction()
    if authd_running():
        print("AUTHD_OK already running")
        return 0
    print("AUTHD starting elevated...")
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Start-Process powershell -Verb RunAs -Wait -ArgumentList "
            "'-NoProfile','-Command','Start-Service VMAuthdService'",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    click_uac_yes()
    for _ in range(20):
        if authd_running():
            print("AUTHD_OK")
            return 0
        time.sleep(1)
    print("AUTHD_FAIL still stopped")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
