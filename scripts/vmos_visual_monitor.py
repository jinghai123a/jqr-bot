#!/usr/bin/env python3
"""双机 UI 状态快照：describe_screen_context + 可选 screencap。"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _adb_serial(port: str) -> str:
    for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
        r = subprocess.run(
            ["adb", "-s", host, "shell", "echo", "OK"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if r.returncode == 0 and "OK" in (r.stdout or ""):
            return host
    return f"127.0.0.1:{port}"


def snapshot(side: str, port: str, bot: dict, *, capture: bool) -> dict:
    import bot_55chat_daemon as d  # noqa: WPS433

    serial = _adb_serial(port)
    root = d.ui_hierarchy(serial)
    ctx = d.describe_screen_context(root, bot, serial)
    model = ""
    try:
        r = subprocess.run(
            ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        model = (r.stdout or "").strip()
    except Exception:
        pass

    cap_path = ""
    if capture:
        cap_dir = Path(os.environ.get("W49_VISUAL_CAPTURE_DIR", ROOT / "logs" / "visual-captures"))
        cap_dir.mkdir(parents=True, exist_ok=True)
        remote = f"/sdcard/w49_visual_{side}.png"
        local = cap_dir / f"{side}_{int(time.time())}.png"
        subprocess.run(["adb", "-s", serial, "shell", "screencap", "-p", remote], timeout=20, check=False)
        subprocess.run(["adb", "-s", serial, "pull", remote, str(local)], timeout=25, check=False)
        if local.is_file() and local.stat().st_size > 1000:
            cap_path = str(local)

    line = (
        f"{side} {serial} state={ctx.page} title={ctx.title!r} "
        f"model={model!r} capture={cap_path or '-'}"
    )
    print(line, flush=True)
    return {
        "side": side,
        "serial": serial,
        "state": ctx.page,
        "title": ctx.title,
        "model": model,
        "capture": cap_path,
        "in_target": ctx.page == "target_group",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listener", action="store_true")
    parser.add_argument("--clicker", action="store_true")
    parser.add_argument("--both", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()

    _load_env_file(ROOT / "config" / "bot-start.env")
    group = os.environ.get("BOT_TARGET_GROUP", "苍井空测试").strip()
    listener_port = os.environ.get("BOT_LISTENER_ADB_PORT", "58433")
    clicker_port = os.environ.get("BOT_CLICKER_ADB_PORT", "52840")
    listener_bot = {"id": "bot-4", "associatedGroup": group}
    clicker_bot = {"id": "bot-3", "associatedGroup": group}

    sides: list[tuple[str, str, dict]] = []
    if args.both or (not args.listener and not args.clicker):
        sides = [
            ("listener", listener_port, listener_bot),
            ("clicker", clicker_port, clicker_bot),
        ]
    else:
        if args.listener:
            sides.append(("listener", listener_port, listener_bot))
        if args.clicker:
            sides.append(("clicker", clicker_port, clicker_bot))

    rc = 0
    rounds = 1 if args.once else 3
    for i in range(rounds):
        if rounds > 1:
            print(f"--- round {i + 1}/{rounds} ---", flush=True)
        for side, port, bot in sides:
            try:
                info = snapshot(side, port, bot, capture=args.capture or args.once)
                if side == "listener" and info["state"] in ("launcher", "offline", "other"):
                    rc = 1
                if not info["in_target"]:
                    rc = 1
            except Exception as exc:
                print(f"{side} ERROR {exc}", flush=True)
                rc = 1
        if i + 1 < rounds:
            time.sleep(5)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
