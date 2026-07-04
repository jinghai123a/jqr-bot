#!/usr/bin/env python3
"""全局断点检查：宿主机 + VM 部署闭环。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def row(name: str, ok: bool, detail: str = "") -> None:
    print(f"{name}\t{'PASS' if ok else 'FAIL'}\t{detail[:100]}")


def main() -> int:
    fails = 0

    # 宿主机
    r = subprocess.run([sys.executable, str(ROOT / "scripts/local_vm/host_test_suite.py")], cwd=ROOT)
    row("host_test_suite", r.returncode == 0)
    if r.returncode:
        fails += 1

    cfg_path = ROOT / "config" / "local-vm.env"
    row("local-vm.env exists", cfg_path.is_file())
    if not cfg_path.is_file():
        fails += 1
        print(f"\nGLOBAL: FAIL ({fails} breakpoints)")
        return 1

    from bot_ops.config import _parse_env_file

    cfg = _parse_env_file(cfg_path)
    host = (cfg.get("VM_HOST") or "").strip()
    row("VM_HOST configured", bool(host), host or "empty")

    vmrun = Path(r"C:\Users\haijin\VMware\Installation\vmrun.exe")
    vmx = Path(r"C:\w49-edge-lab\w49-edge-lab.vmx")
    if vmrun.is_file() and vmx.is_file():
        lst = subprocess.run([str(vmrun), "list"], capture_output=True, text=True, timeout=30)
        running = str(vmx).lower() in (lst.stdout or "").lower()
        row("VM running", running)
        if not running:
            fails += 1
        ipr = subprocess.run(
            [str(vmrun), "-T", "ws", "getGuestIPAddress", str(vmx)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        tools = "Tools are not running" not in (ipr.stderr or ipr.stdout or "")
        row("VMware Tools", tools, (ipr.stdout or ipr.stderr or "").strip()[:80])
        if not tools:
            fails += 1
    else:
        row("VMware vmrun", False, "missing")
        fails += 1

    try:
        from scripts.local_vm.host_deploy import load_vm_config, run_ssh, ssh_client

        with ssh_client(load_vm_config()) as c:
            row("guest SSH", True, host)
            checks = [
                ("test -d /opt/55m-lab/app && echo yes", "VM app dir"),
                ("test -f /opt/55m-lab/app/edge_brain/__init__.py && echo yes", "edge_brain synced"),
                ("systemctl is-active edge-brain 2>/dev/null || echo no", "edge-brain systemd"),
            ]
            for cmd, label in checks:
                out = run_ssh(c, cmd, timeout=15).strip()
                ok = "yes" in out if "dir" in label or "synced" in label else "active" in out
                row(label, ok, out)
                if not ok:
                    fails += 1
            health = run_ssh(
                c,
                'curl -sf -H "Authorization: Bearer w49-edge-local" http://127.0.0.1:8790/health || echo FAIL',
                timeout=15,
            ).strip()
            row("VM edge :8790", "FAIL" not in health, health[:80])
            if "FAIL" in health:
                fails += 1
    except Exception as ex:
        row("guest SSH / deploy", False, str(ex)[:100])
        fails += 1

    print(f"\nGLOBAL: {'PASS' if fails == 0 else f'FAIL ({fails} breakpoints)'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
