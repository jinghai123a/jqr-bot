#!/usr/bin/env python3
"""Test VMOS tunnel SSH auth on VPS (sshpass -f)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
snap = json.loads((ROOT / "config/vmos-console-snapshot.json").read_text(encoding="utf-8"))

REMOTE_PY = r'''
import json, os, subprocess, sys, tempfile
snap = json.loads(sys.stdin.read())
R = "/home/bot/55chat-bot"

def try_ssh(side, use_bind):
    c = snap[side]
    pw = c["ssh_pass"]
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(pw)
        pf = f.name
    os.chmod(pf, 0o600)
    args = ["sshpass", "-f", pf, "ssh"]
    if use_bind:
        args += ["-b", c["tunnel_bind"]]
    args += [
        "-oBatchMode=yes", "-oStrictHostKeyChecking=accept-new", "-oConnectTimeout=15",
        "-p", str(c["console_ssh_port"]), f"{c['console_ssh_user']}@{c['console_ssh_host']}",
        "echo", "AUTH_OK",
    ]
    r = subprocess.run(args, capture_output=True, text=True, timeout=25)
    os.unlink(pf)
    out = (r.stdout + r.stderr).strip()[:250]
    print(f"{side} bind={use_bind} rc={r.returncode} {out}")

for side in ("right", "left"):
    for b in (False, True):
        try_ssh(side, b)
'''


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".py") as tmp:
            tmp.write(REMOTE_PY)
            tmp_path = tmp.name
        remote = f"{R}/scripts/vps_ssh_auth_test.py"
        try:
            ssh.sftp_put(tmp_path, remote)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        payload = json.dumps(snap)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json") as j:
            j.write(payload)
            jpath = j.name
        try:
            ssh.sftp_put(jpath, f"{R}/data/_snap_test.json")
        finally:
            Path(jpath).unlink(missing_ok=True)
        print(ssh.run(f"python3 {remote} < {R}/data/_snap_test.json", 90))
        print("=== reconnect ===")
        print(ssh.run(f"bash {R}/scripts/tunnel-right.sh 2>&1", 120)[-400:])
        print(ssh.run(f"bash {R}/scripts/tunnel-left.sh 2>&1", 120)[-400:])
        print(ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 25))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
