#!/usr/bin/env python3
"""Push VMOS creds to VPS, run OpenAPI refresh ON VPS (avoid local IP rate limit)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import _parse_env_file, load_vps_config
from bot_ops.deploy_secrets import push_runtime_secrets
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"

REMOTE_ONCE = r"""
import json, sys
from pathlib import Path
ROOT = Path(%r)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from bot_tunnel.daemon import build_daemon_sides, run_daemon_cycle, DaemonConfig
from bot_tunnel.env_io import load_env_file
from vmos_api_client import VmosApiClient

def client():
    e = load_env_file(ROOT / "config" / "vmos-api.env")
    ak = e.get("VMOS_ACCESS_KEY") or e.get("VMOS_AK")
    sk = e.get("VMOS_SECRET_KEY") or e.get("VMOS_SK")
    if not ak or not sk:
        raise SystemExit("missing VMOS keys on VPS")
    return VmosApiClient(ak, sk, timeout=120)

pads_cfg = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
sides = build_daemon_sides(ROOT)
sides["right"]["local_port"] = str((pads_cfg.get("right") or {}).get("local_port") or "58433")
sides["left"]["local_port"] = str((pads_cfg.get("left") or {}).get("local_port") or "55612")

# right only first
right = sides["right"]
left = sides["left"]
c = client()
pads, models = [], {}
try:
    pads = c.list_pads(page=1, rows=50)
    print("list_pads", len(pads))
except Exception as exc:
    print("list_pads skip", exc)

from bot_tunnel import refresh_side_credentials, resolve_pad_code
for side, cfg in [("right", right), ("left", left)]:
    code = resolve_pad_code(side, cfg, pads, {})
    print("=== refresh", side, code, cfg["local_port"], "===")
    ok, fail = refresh_side_credentials(side, cfg, c, pads, {}, max_attempts=4)
    print("result", side, ok, fail)

import subprocess
for sh in ("reconnect-dual-adb.sh",):
    r = subprocess.run(["bash", str(ROOT / "scripts" / sh)], cwd=ROOT, capture_output=True, text=True, timeout=300)
    print(r.stdout[-2000:] if r.stdout else r.stderr[-2000:])
for sh in ("tunnel-right.sh", "tunnel-left.sh"):
    r = subprocess.run(["bash", str(ROOT / "scripts" / sh)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    print("---", sh, "---")
    print((r.stdout or r.stderr)[-800:])
r = subprocess.run(["adb", "-P", "5038", "devices", "-l"], capture_output=True, text=True)
print("5038", r.stdout)
r = subprocess.run(["adb", "-P", "5039", "devices", "-l"], capture_output=True, text=True)
print("5039", r.stdout)
""" % R


def _sync_local_vmos_api() -> None:
    env = _parse_env_file(ROOT / "config" / "vmos-api.env")
    doc = ROOT / "config" / "本地-VMOS-开发者凭证.md"
    if doc.is_file():
        text = doc.read_text(encoding="utf-8")
        for label, key in (
            ("Access Key ID", "VMOS_ACCESS_KEY"),
            ("Secret Access Key", "VMOS_SECRET_KEY"),
        ):
            marker = f"| {label} | `"
            if marker in text:
                s = text.index(marker) + len(marker)
                t = text.index("`", s)
                env[key] = text[s:t].strip()
    ak = env.get("VMOS_ACCESS_KEY", "")
    sk = env.get("VMOS_SECRET_KEY", "")
    if len(ak) < 10 or len(sk) < 20:
        raise RuntimeError(f"incomplete VMOS creds AK={len(ak)} SK={len(sk)}")
    (ROOT / "config" / "vmos-api.env").write_text(
        f"VMOS_ACCESS_KEY={ak}\nVMOS_SECRET_KEY={sk}\n"
        f"VMOS_CALLBACK_URL=http://195.114.193.136:3000/api/vmos/callback\n",
        encoding="utf-8",
    )
    print(f"synced vmos-api.env AK={len(ak)} SK={len(sk)}")


def main() -> int:
    _sync_local_vmos_api()
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        ssh.run(
            "pkill -9 -f vps_force_left_tunnel_loop; pkill -9 -f vmos_adb_daemon; "
            f"rm -f {R}/logs/.vmos-refresh.lock; true",
            15,
        )
        pushed = push_runtime_secrets(ssh, ROOT, R)
        print("pushed", pushed)
        for k, v in (
            ("BOT_LISTENER_ADB_PORT", "58433"),
            ("BOT_CLICKER_ADB_PORT", "55612"),
            ("BOT_ADB_ISOLATED", "1"),
        ):
            ssh.run(
                f"grep -q '^{k}=' {R}/config/bot-start.env && "
                f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || "
                f"echo '{k}={v}' >> {R}/config/bot-start.env",
                12,
            )
        remote_py = f"{R}/scripts/_vps_openapi_refresh_inline.py"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".py") as tmp:
            tmp.write(REMOTE_ONCE)
            tmp_path = tmp.name
        try:
            ssh.sftp_put(tmp_path, remote_py)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        print("=== VPS OpenAPI refresh (600s) ===")
        out = ssh.run(f"cd {R} && timeout 600 {PY} {remote_py} 2>&1", 620)
        print(out)
        print(ssh.run(f"bash {R}/scripts/vmos_adb_daemon_start.sh start 2>&1", 30))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
