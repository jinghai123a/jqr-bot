#!/usr/bin/env python3
"""本地 5 期门控链：timeline → settle-bundle → settle-done → open-job。"""
from __future__ import annotations

import argparse
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

_JWT = ensure_jwt_env()
HDR = {"Authorization": f"Bearer {_JWT}", "Content-Type": "application/json"}


def api(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=HDR, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def one_round(i: int) -> bool:
    code, tl = api("GET", "/edge/timeline")
    if code != 200:
        print(f"R{i} FAIL timeline {code}")
        return False
    rid = int((tl if isinstance(tl, dict) else {}).get("pending_rid") or 1000 + i)
    code, bundle = api("GET", f"/settle-bundle?period={rid}")
    bundle_ok = code in (200, 404)
    code2, done = api("POST", "/settle-done", {"period": rid, "images_ok": True, "device": "local-sim"})
    if code2 != 200:
        print(f"R{i} FAIL settle-done {code2} {done}")
        return False
    gates = (done if isinstance(done, dict) else {}).get("gates") or {}
    code3, job = api("GET", f"/edge/open-job?period={rid + 1}")
    open_ok = code3 == 200 and isinstance(job, dict)
    ok = bundle_ok and bool(gates.get("open")) and open_ok
    print(f"R{i} rid={rid} bundle={code} open={gates.get('open')} open_rid={gates.get('open_rid')} -> {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    proc = subprocess.Popen(
        [sys.executable, "-m", "edge_brain"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f"{BASE}/health", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        passed = sum(1 for i in range(1, args.rounds + 1) if one_round(i))
        print(f"FIVE_ROUND {passed}/{args.rounds}")
        return 0 if passed == args.rounds else 1
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
