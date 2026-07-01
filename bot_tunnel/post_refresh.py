"""After OpenAPI refresh: mandatory dual-tunnel verify (automatic, not manual)."""
from __future__ import annotations

import subprocess
from pathlib import Path

RunSubprocess = subprocess.run


def verify_dual_tunnels(
    root: Path,
    *,
    run_subprocess: RunSubprocess = subprocess.run,
) -> tuple[bool, str]:
    """Run vps_post_task_tunnel_verify.sh — both 58433+52840 must adb shell OK."""
    script = root / "scripts" / "vps_post_task_tunnel_verify.sh"
    if not script.is_file():
        return False, f"missing {script}"
    r = run_subprocess(
        ["bash", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out


def maintenance_tunnel_cycle(
    root: Path,
    *,
    refresh_cmd: list[str],
    run_subprocess: RunSubprocess = subprocess.run,
    max_refresh_attempts: int = 2,
) -> tuple[bool, str]:
    """Automatic maintenance closure: refresh → verify → retry refresh if verify fails."""
    logs: list[str] = []
    for attempt in range(1, max_refresh_attempts + 1):
        logs.append(f"=== refresh attempt {attempt} ===")
        r = run_subprocess(
            refresh_cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
        )
        chunk = (r.stdout or "") + (r.stderr or "")
        logs.append(chunk)
        if r.returncode != 0:
            logs.append(f"refresh exit={r.returncode}")
        ok, vout = verify_dual_tunnels(root, run_subprocess=run_subprocess)
        logs.append(vout)
        if ok:
            logs.append("TUNNEL_MAINTENANCE_OK verify passed")
            return True, "\n".join(logs)
        logs.append(f"verify failed after refresh attempt {attempt}")
    logs.append("TUNNEL_MAINTENANCE_FAIL")
    return False, "\n".join(logs)
