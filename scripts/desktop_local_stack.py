#!/usr/bin/env python3
"""本机桌面全栈：mock panel :3000 + edge_brain :8790 + 公告编排（WS 5600）。"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCS: list[subprocess.Popen] = []
DETACHED: list[subprocess.Popen] = []
PY = os.environ.get("DESKTOP_PYTHON") or str(
    ROOT / ".venv" / "Scripts" / "python.exe"
    if (ROOT / ".venv" / "Scripts" / "python.exe").is_file()
    else sys.executable
)


def _health(url: str, sec: float = 20.0) -> bool:
    deadline = time.time() + sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def _spawn(cmd: list[str], *, env: dict[str, str] | None = None, detach: bool = False) -> subprocess.Popen:
    merged = {**os.environ, **(env or {})}
    kwargs: dict = {"cwd": str(ROOT), "env": merged}
    if detach and sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    p = subprocess.Popen(cmd, **kwargs)
    if detach:
        DETACHED.append(p)
    else:
        PROCS.append(p)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="仅验 panel/brain/WS")
    args = ap.parse_args()

    env = {
        "EDGE_BRAIN_JWT_SECRET": "w49-local-desktop-test",
        "EDGE_BRAIN_HOST": "0.0.0.0",
        "EDGE_BRAIN_PORT": "8790",
        "BOT_PANEL_URL": "http://127.0.0.1:3000",
        "BOT_API_BASE": "http://127.0.0.1:3000",
        "BOT_55WS_URL": os.environ.get("BOT_55WS_URL", "ws://127.0.0.1:5600"),
        "BOT_TARGET_GROUP": os.environ.get("BOT_TARGET_GROUP", "苍井空测试"),
        "DESKTOP_GROUP_ID": os.environ.get("DESKTOP_GROUP_ID", "492316"),
        "EDGE_MOCK_GROUP_LEFT": os.environ.get("BOT_TARGET_GROUP", "苍井空测试"),
        "EDGE_MOCK_GROUP_RIGHT": os.environ.get("BOT_TARGET_GROUP", "苍井空测试"),
        "PYTHONUNBUFFERED": "1",
    }

    if not _health("http://127.0.0.1:3000/api/bots", 2.0):
        _spawn([PY, str(ROOT / "scripts" / "edge_mock_panel.py")], env=env, detach=True)
    if not _health("http://127.0.0.1:8790/health", 2.0):
        _spawn([PY, "-m", "edge_brain"], env=env, detach=True)

    if not _health("http://127.0.0.1:3000/api/bots"):
        print("panel FAIL", file=sys.stderr)
        return 1
    if not _health("http://127.0.0.1:8790/health"):
        print("edge_brain FAIL", file=sys.stderr)
        return 1

    with urllib.request.urlopen("http://127.0.0.1:3000/api/settings", timeout=3) as r:
        if r.status != 200:
            print("panel settings FAIL", file=sys.stderr)
            return 1

    print("LOCAL_DESKTOP_STACK_OK panel=:3000 brain=:8790 ws=" + env["BOT_55WS_URL"])
    if args.check:
        return 0

    lock = ROOT / "data" / ".desktop_announce.lock"
    if lock.is_file():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip() or "0")
            if pid > 0:
                import ctypes
                k = ctypes.windll.kernel32
                h = k.OpenProcess(0x1000, False, pid)
                if h:
                    k.CloseHandle(h)
                    print(f"announce 已在跑 pid={pid}，跳过重复启动", flush=True)
                    return 0
        except (OSError, ValueError):
            pass

    ann = subprocess.Popen(
        [PY, str(ROOT / "scripts" / "desktop_local_announce.py")],
        cwd=str(ROOT),
        env={**os.environ, **env},
    )
    PROCS.append(ann)
    print("公告编排已启动 — 68助手保持登录，群=苍井空测试", flush=True)
    try:
        ann.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in PROCS:
            p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
