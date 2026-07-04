#!/usr/bin/env python3
"""
124 edge AUTO 闭环：测试 → UI-TARS 本机窗 → 隧道直刷 → 回群 → 视觉 → verify。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).resolve().parent
R = "/home/bot/55chat-bot"
ART = ROOT / "artifacts" / "edge-auto-closure.json"

sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402


def run_local(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600) -> tuple[int, str]:
    r = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def _safe_text(s: str) -> str:
    return s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def main() -> int:
    report: dict = {"ts_utc": datetime.now(timezone.utc).isoformat(), "steps": []}
    rc = 0

    def step(name: str, ok: bool, detail: str) -> None:
        nonlocal rc
        if not ok:
            rc = 1
        report["steps"].append({"name": name, "ok": ok, "detail": detail[:2000]})
        mark = "PASS" if ok else "FAIL"
        print(f"\n[{mark}] {name}\n{_safe_text(detail)[:1200]}", flush=True)

    print("=== 1/7 pytest (edge) ===", flush=True)
    code, out = run_local(
        [sys.executable, "-m", "pytest", "tests/test_edge_brain.py", "tests/test_announce_locked.py", "-q"],
        timeout=120,
    )
    step("pytest", code == 0, out)

    print("=== 2/7 UI-TARS 本机窗口 ===", flush=True)
    code, out = run_local([sys.executable, str(BASE / "w49_uitars_vmos_probe.py")], timeout=90)
    step("uitars_local", code == 0, out)

    print("=== 3/7 VMOS 隧道直刷（跳过 list_pads）===", flush=True)
    code, out = run_local([sys.executable, str(BASE / "vmos_direct_adb_refresh.py")], timeout=240)
    if code != 0:
        out += "\n[fallback] tunnel API failed — VPS heal only\n"
        code2, out2 = run_local([sys.executable, str(BASE / "edge_vps_heal_only.py")], timeout=420)
        step("tunnel_or_vps_heal", code2 == 0, out + out2)
        report["rc"] = 0 if code2 == 0 else 1
        ART.parent.mkdir(parents=True, exist_ok=True)
        ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if code2 == 0:
            print("EDGE_AUTO_CLOSURE_OK (vps_heal_fallback)", flush=True)
        return 0 if code2 == 0 else 1
    step("tunnel_direct_refresh", True, out)

    try:
        config = load_vps_config(ROOT)
    except Exception as exc:
        step("vps_ssh", False, str(exc))
        ART.parent.mkdir(parents=True, exist_ok=True)
        ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    upload_names = (
        "recover_listener_now.py",
        "vmos_visual_monitor.py",
        "w49_uitars_vmos_probe.py",
    )
    print("=== 4/7 上传辅助脚本 ===", flush=True)
    with VpsSSH(config) as ssh:
        for name in upload_names:
            local = BASE / name
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/scripts/{name}")
        pads = ROOT / "config" / "vmos-pads.json"
        if pads.is_file():
            ssh.sftp_put(str(pads), f"{R}/config/vmos-pads.json")
    step("upload_scripts", True, f"uploaded {', '.join(upload_names)}")

    print("=== 5/7 双机回群（隧道已刷，复核）===", flush=True)
    with VpsSSH(config) as ssh:
        recover_out = ssh.run(f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 150)
        step(
            "recover_groups",
            "in_group=True" in recover_out or "page=target_group" in recover_out,
            recover_out,
        )

        print("=== 6/7 视觉 + 型号 ===", flush=True)
        visual_out = ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"python3 {R}/scripts/vmos_visual_monitor.py --both --once --capture 2>&1",
            90,
        )
        left_model = ssh.run(
            f"adb -s 127.0.0.1:{config.clicker_adb_port} shell getprop ro.product.model 2>/dev/null || true",
            20,
        ).strip()
        right_model = ssh.run(
            f"adb -s 127.0.0.1:{config.listener_adb_port} shell getprop ro.product.model 2>/dev/null || true",
            20,
        ).strip()
        model_ok = "pixel" in left_model.lower() or "Pixel" in left_model
        step(
            "visual_and_model",
            "state=target_group" in visual_out and model_ok,
            f"{visual_out}\nleft_model={left_model!r} right_model={right_model!r}",
        )

    time.sleep(8)
    print("=== 7/7 verify_dual_brain ===", flush=True)
    code, out = run_local([sys.executable, str(BASE / "verify_dual_brain.py")], timeout=180)
    step("verify_dual_brain", code == 0, out)

    report["rc"] = rc
    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport -> {ART}", flush=True)
    if rc == 0:
        print("EDGE_AUTO_CLOSURE_OK", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
