#!/usr/bin/env python3
"""Sync VMOS creds + tunnel env to VPS, reconnect dual ADB (no OpenAPI if busy)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import _parse_env_file, load_vps_config
from bot_ops.deploy_secrets import push_runtime_secrets
from bot_ops.ssh_client import VpsSSH
from bot_ops.vps_ports import dual_adb_online, dual_adb_ports

R = "/home/bot/55chat-bot"


def _sync_vmos_api() -> None:
    env = _parse_env_file(ROOT / "config" / "vmos-api.env")
    doc = ROOT / "config" / "本地-VMOS-开发者凭证.md"
    if doc.is_file():
        text = doc.read_text(encoding="utf-8")
        for label, key in (("Access Key ID", "VMOS_ACCESS_KEY"), ("Secret Access Key", "VMOS_SECRET_KEY")):
            m = f"| {label} | `"
            if m in text:
                s = text.index(m) + len(m)
                e = text.index("`", s)
                env[key] = text[s:e].strip()
    (ROOT / "config" / "vmos-api.env").write_text(
        f"VMOS_ACCESS_KEY={env['VMOS_ACCESS_KEY']}\n"
        f"VMOS_SECRET_KEY={env['VMOS_SECRET_KEY']}\n"
        f"VMOS_CALLBACK_URL=http://195.114.193.136:3000/api/vmos/callback\n",
        encoding="utf-8",
    )


def main() -> int:
    _sync_vmos_api()
    rport, lport = dual_adb_ports(ROOT)
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        for k, v in (
            ("BOT_LISTENER_ADB_PORT", rport),
            ("BOT_CLICKER_ADB_PORT", lport),
            ("BOT_ADB_ISOLATED", "1"),
        ):
            ssh.run(
                f"grep -q '^{k}=' {R}/config/bot-start.env && "
                f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || echo '{k}={v}' >> {R}/config/bot-start.env",
                12,
            )
        print("pushed", push_runtime_secrets(ssh, ROOT, R))
        print("=== OpenAPI right-first (VPS, 300s) ===")
        print(
            ssh.run(
                f"cd {R} && timeout 300 .venv/bin/python3 -c \""
                "import json,sys; from pathlib import Path; R=Path('.'); "
                "sys.path[:0]=[str(R),str(R/'scripts')]; "
                "from bot_tunnel.env_io import load_env_file; from vmos_api_client import VmosApiClient; "
                "from bot_tunnel import refresh_side_credentials, resolve_pad_code; "
                "e=load_env_file(R/'config/vmos-api.env'); c=VmosApiClient(e['VMOS_ACCESS_KEY'],e['VMOS_SECRET_KEY'],timeout=90); "
                "pads=json.loads((R/'config/vmos-pads.json').read_text()); "
                "cfg={**(pads.get('right') or {}),'local_port':'58433','tunnel_file':R/'config/tunnel-right.env','tunnel_bind':'195.114.193.237'}; "
                "print('right', resolve_pad_code('right',cfg,[],{})); "
                "ok,f=refresh_side_credentials('right',cfg,c,[],{},max_attempts=3); print('done',ok,f)\" 2>&1",
                310,
            )
        )
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -15", 300))
        print(ssh.run(f"bash {R}/scripts/tunnel-right.sh 2>&1 | tail -8", 120))
        print(ssh.run(f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -8", 120))
        out = ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 25)
        print(out)
        ok = dual_adb_online(out, rport, lport)
        if ok:
            ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -10", 360)
        ssh.run(f"bash {R}/scripts/vmos_adb_daemon_start.sh start 2>&1", 25)
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
