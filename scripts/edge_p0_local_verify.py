#!/usr/bin/env python3
"""P0：edge_brain 骨架 + curl settle-bundle + WS 小 JSON。"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8790"

from scripts.edge_auth_util import ensure_jwt_env  # noqa: E402

HDR = {"Authorization": f"Bearer {ensure_jwt_env()}"}


def get(path: str) -> tuple[int, dict | str]:
    req = urllib.request.Request(f"{BASE}{path}", headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode()
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "edge_brain"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"{BASE}/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.25)
        else:
            print("P0_FAIL health")
            return 1
        print("P0 health OK")

        code, tl = get("/edge/timeline")
        if code != 200 or not isinstance(tl, dict) or "rid" not in tl:
            print("P0_FAIL timeline", code, tl)
            return 1
        rid = int(tl.get("rid") or tl.get("open_rid") or 0)
        print(f"P0 timeline OK pending_rid={rid}")

        code, bundle = get(f"/settle-bundle?period={rid}")
        if code == 404:
            print(f"P0 settle-bundle 404 rid={rid} (28.run 未开奖，骨架通)")
        elif code == 200 and isinstance(bundle, dict) and "images" in bundle:
            imgs = bundle.get("images") or {}
            print(f"P0 settle-bundle OK keys={list(imgs.keys())[:3]} etag_ts={bundle.get('server_ts')}")
        else:
            print("P0_FAIL settle-bundle", code, str(bundle)[:200])
            return 1

        try:
            import websocket  # type: ignore
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "websocket-client"])
            import websocket  # type: ignore

        ws_url = f"ws://127.0.0.1:8790/ws?token={ensure_jwt_env()}"
        msg = json.loads(websocket.create_connection(ws_url, timeout=5).recv())
        if msg.get("topic") != "hello":
            print("P0_FAIL ws", msg)
            return 1
        print("P0 WS hello OK (small JSON)")

        apk = ROOT / "config" / "55m-knowledge" / "oss-stack.json"
        if apk.is_file():
            data = json.loads(apk.read_text(encoding="utf-8"))
            autojs = next((s for s in data.get("stacks", []) if s.get("id") == "autojs6"), {})
            print(f"P0 AutoJs6 APK pinned: {autojs.get('apk_url', '')[:60]}...")

        print("P0_OK")
        return 0
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
