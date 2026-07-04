#!/usr/bin/env python3
"""Step1：架构实况审计（云机内验真优先，日志仅辅助）。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "artifacts" / "step1-architecture-audit.json"


def _ssh_audit() -> dict:
    from bot_ops.config import load_vps_config
    from bot_ops.ssh_client import VpsSSH

    R = "/home/bot/55chat-bot"
    out: dict = {}
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        out["processes"] = ssh.run(
            "pgrep -af 'bot_dual_supervisor|edge_brain|edge_adb_agent|spawn' | grep -v pgrep | head -12",
            20,
        ).strip()
        out["adb_devices"] = ssh.run("adb devices -l 2>/dev/null | head -10", 15).strip()
        out["right_model"] = ssh.run(
            "adb -P 5038 -s 127.0.0.1:58433 shell getprop ro.product.model 2>/dev/null | tr -d '\\r'",
            15,
        ).strip()
        out["left_model"] = ssh.run(
            "adb -P 5039 -s 127.0.0.1:52840 shell getprop ro.product.model 2>/dev/null | tr -d '\\r'",
            15,
        ).strip()
        out["right_wm"] = ssh.run(
            "adb -P 5038 -s 127.0.0.1:58433 shell wm size 2>/dev/null | tr -d '\\r'",
            15,
        ).strip()
        out["left_wm"] = ssh.run(
            "adb -P 5039 -s 127.0.0.1:52840 shell wm size 2>/dev/null | tr -d '\\r'",
            15,
        ).strip()
        out["edge_brain"] = ssh.run("curl -sf http://127.0.0.1:8790/health 2>/dev/null || echo FAIL", 10).strip()
        out["env_roles"] = ssh.run(
            f"grep -E 'BOT_LISTENER_ID|BOT_CLICKER|BOT_DUAL|BOT_EDGE|BOT_ANNOUNCE' {R}/config/bot-start.env | head -20",
            15,
        ).strip()
        out["tunnel_right_head"] = ssh.run(f"head -8 {R}/config/tunnel-right.env 2>/dev/null", 10).strip()
        out["tunnel_left_head"] = ssh.run(f"head -8 {R}/config/tunnel-left.env 2>/dev/null", 10).strip()
        out["recent_gallery"] = ssh.run(
            f"grep -E '勾选图片|批量发图成功|gallery_check' {R}/logs/dual-supervisor.log 2>/dev/null | tail -5",
            20,
        ).strip()
        out["recent_open"] = ssh.run(
            f"grep -E 'b64\\+announce|开局公告' {R}/logs/dual-supervisor.log 2>/dev/null | tail -5",
            20,
        ).strip()
    return out


def _vmos_pads() -> dict:
    try:
        import paramiko

        R = "/home/bot/55chat-bot"
        from bot_ops.config import load_vps_config

        cfg = load_vps_config(ROOT)
        with paramiko.SSHClient() as s:
            s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            s.connect(cfg.host, username=cfg.user, password=cfg.password, timeout=30)
            _, o, _ = s.exec_command(f"cd {R} && .venv/bin/python3 scripts/vmos-refresh-tunnels.py --list 2>&1 | tail -40", timeout=120)
            return {"list_output": (o.read().decode("utf-8", "replace")).strip()}
    except Exception as ex:
        return {"error": str(ex)}


def main() -> int:
    payload = {
        "ts": datetime.now(tz=ZoneInfo("Asia/Shanghai")).isoformat(),
        "vision": {
            "right": "bot-4 LISTENER @58433 — warn/close/open 文字",
            "left": "bot-3 CLICKER @52840 — 结算三图",
            "brain": "edge_brain:8790 + Panel:3000 + Gateway:8765",
            "executor": "bot_dual_supervisor spawn×2（生产）",
        },
        "live": _ssh_audit(),
        "vmos": _vmos_pads(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
