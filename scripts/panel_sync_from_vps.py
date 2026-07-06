#!/usr/bin/env python3
"""从 VPS Panel :3000 拉取 products/settings/bots 快照到本地知识库。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "config" / "55m-knowledge" / "panel-production-snapshot.json"
R = "/home/bot/55chat-bot"


def main() -> int:
    from bot_ops.config import load_vps_config
    from bot_ops.ssh_client import VpsSSH

    cfg = load_vps_config(ROOT)
    snap: dict = {"source": f"http://{cfg.host}:3000", "fetched": {}}

    with VpsSSH(cfg) as ssh:
        for key, path in (
            ("bots", "/api/bots"),
            ("settings", "/api/settings"),
            ("products", "/api/products"),
            ("combo_rules", "/api/combo-rules"),
        ):
            raw = ssh.run(f"curl -sf --max-time 8 http://127.0.0.1:3000{path}", 20).strip()
            if not raw:
                print(f"WARN empty {path}")
                continue
            try:
                snap["fetched"][key] = json.loads(raw)
            except json.JSONDecodeError:
                snap["fetched"][key] = raw[:500]
            print(f"OK {path} len={len(raw)}")

        ui = ssh.run(
            f"ls -d {R}/panel {R}/frontend {R}/client 2>/dev/null; "
            f"find {R} -maxdepth 2 -type f \\( -name 'index.html' -o -name 'package.json' \\) 2>/dev/null | head -8",
            25,
        )
        snap["vps_ui_paths"] = ui.strip()

        proc = ssh.run("pgrep -af 'node' 2>/dev/null | head -8", 15)
        snap["vps_node_procs"] = proc.strip()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
