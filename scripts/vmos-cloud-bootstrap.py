#!/usr/bin/env python3
"""VMOS 双机一键部署：端口对齐、隧道续期、剪贴板、保活、cron/systemd。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from vmos_api_client import VmosApiClient  # noqa: E402

BOT_ENV = ROOT / "config" / "bot-start.env"
PADS_JSON = ROOT / "config" / "vmos-pads.json"
API_ENV = ROOT / "config" / "vmos-api.env"
WUWU_PKG = "wuwu.d260619.t0600.d9vlmf481w"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def patch_bot_env() -> None:
    text = BOT_ENV.read_text(encoding="utf-8")
    if "BOT_CLICKER_ADB_PORT=58851" in text:
        text = text.replace("BOT_CLICKER_ADB_PORT=58851", "BOT_CLICKER_ADB_PORT=52840")
        BOT_ENV.write_text(text, encoding="utf-8")
        print("[ok] bot-start.env CLICKER port -> 52840")
    else:
        print("[skip] bot-start.env CLICKER port already aligned")

    if PADS_JSON.exists():
        pads = json.loads(PADS_JSON.read_text(encoding="utf-8"))
        left = pads.get("left") or {}
        if left.get("local_port") != 52840:
            left["local_port"] = 52840
            pads["left"] = left
            PADS_JSON.write_text(json.dumps(pads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("[ok] vmos-pads.json left local_port -> 52840")


def vmos_keepalive_and_apps(client: VmosApiClient, pads: dict[str, str]) -> None:
    codes = list(pads.values())
    try:
        client.open_adb(codes)
        print("[ok] openOnlineAdb")
    except RuntimeError as exc:
        print(f"[warn] openOnlineAdb: {exc}")

    detail = client.pad_info(codes["right"]) if "right" in codes else {}
    if detail:
        print(f"[pad] right {detail.get('padCode')} android={detail.get('androidVersion')}")
    if "left" in codes:
        d2 = client.pad_info(codes["left"])
        if d2:
            print(f"[pad] left {d2.get('padCode')} android={d2.get('androidVersion')}")

    for code in codes:
        try:
            client.set_keep_alive_app([code], WUWU_PKG)
            print(f"[ok] setKeepAliveApp {code}")
        except RuntimeError as exc:
            print(f"[warn] setKeepAliveApp {code}: {exc}")
        try:
            client.start_app([code], WUWU_PKG)
            print(f"[ok] startApp 55M {code}")
        except RuntimeError as exc:
            print(f"[warn] startApp {code}: {exc}")


def install_cron() -> None:
    cron_lines = [
        "*/2 * * * * /home/bot/55chat-bot/scripts/vmos-dual-watchdog.sh",
        "0 3 * * * cd /home/bot/55chat-bot && python3 scripts/vmos-refresh-tunnels.py --reconnect >> logs/vmos-refresh.log 2>&1",
    ]
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = cur.stdout if cur.returncode == 0 else ""
    kept = [
        ln for ln in existing.splitlines()
        if ln.strip() and "55chat-bot" not in ln and "54936" not in ln and "58851" not in ln
    ]
    new_cron = "\n".join(kept + cron_lines) + "\n"
    subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True)
    print("[ok] crontab updated")


def install_systemd_watchdog() -> None:
    unit = """[Unit]
Description=VMOS dual ADB watchdog (54936 + 52840)
After=network-online.target

[Service]
Type=oneshot
ExecStart=/home/bot/55chat-bot/scripts/vmos-dual-watchdog.sh
"""
    timer = """[Unit]
Description=Check dual ADB every 2 minutes

[Timer]
OnBootSec=90s
OnUnitActiveSec=2min
Persistent=true
Unit=vmos-dual-watchdog.service

[Install]
WantedBy=timers.target
"""
    Path("/etc/systemd/system/vmos-dual-watchdog.service").write_text(unit, encoding="utf-8")
    Path("/etc/systemd/system/vmos-dual-watchdog.timer").write_text(timer, encoding="utf-8")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "vmos-dual-watchdog.timer"], check=True)
    print("[ok] vmos-dual-watchdog.timer enabled")


def main() -> int:
    patch_bot_env()

    print("=== refresh tunnels ===")
    for attempt in range(2):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "vmos-refresh-tunnels.py"), "--reconnect"],
            cwd=ROOT,
        )
        if r.returncode == 0:
            break
        print(f"[warn] refresh attempt {attempt + 1} failed, retry in 20s")
        time.sleep(20)
    else:
        print("[warn] API refresh skipped — using existing tunnels")
        subprocess.run(["bash", str(ROOT / "scripts" / "reconnect-dual-adb.sh")], cwd=ROOT, check=False)

    api = load_env(API_ENV)
    ak = api.get("VMOS_ACCESS_KEY") or api.get("VMOS_AK")
    sk = api.get("VMOS_SECRET_KEY") or api.get("VMOS_SK")
    if ak and sk and PADS_JSON.exists():
        pads_cfg = json.loads(PADS_JSON.read_text(encoding="utf-8"))
        codes = {
            "right": (pads_cfg.get("right") or {}).get("pad_code", ""),
            "left": (pads_cfg.get("left") or {}).get("pad_code", ""),
        }
        codes = {k: v for k, v in codes.items() if v}
        if codes:
            print("=== VMOS API keepalive + 55M ===")
            try:
                vmos_keepalive_and_apps(VmosApiClient(ak, sk), codes)
            except Exception as exc:
                print(f"[warn] VMOS API optional step: {exc}")

    print("=== clipboard setup ===")
    subprocess.run(["bash", str(ROOT / "scripts" / "setup-cloud-clipboard.sh")], cwd=ROOT, check=False)

    print("=== cron + systemd ===")
    install_cron()
    try:
        install_systemd_watchdog()
    except subprocess.CalledProcessError as exc:
        print(f"[warn] systemd: {exc}")

    print("=== recover listener + restart bot ===")
    bot = load_env(BOT_ENV)
    rport = bot.get("BOT_LISTENER_ADB_PORT", "54936")
    if Path(ROOT / "scripts" / "redeploy-listener-right.sh").exists():
        subprocess.run(["bash", str(ROOT / "scripts" / "redeploy-listener-right.sh")], cwd=ROOT, check=False)
    else:
        subprocess.run(
            ["bash", "-c", f"cd {ROOT} && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group 127.0.0.1:{rport}"],
            check=False,
        )
        subprocess.run(["bash", str(ROOT / "scripts" / "restart-55chat-bot.sh")], cwd=ROOT, check=False)

    print("=== adb devices ===")
    subprocess.run(["adb", "devices", "-l"])
    print("[done] vmos-cloud-bootstrap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
