"""ADB tunnel reachability probes."""
from __future__ import annotations

import subprocess
from typing import Callable


RunSubprocess = Callable[..., subprocess.CompletedProcess[str]]


def adb_probe_port(port: str, *, run_subprocess: RunSubprocess = subprocess.run) -> bool:
    for serial in (f"127.0.0.1:{port}", f"localhost:{port}"):
        r = run_subprocess(
            ["adb", "-s", serial, "shell", "echo", "OK"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if r.returncode == 0 and "OK" in (r.stdout or ""):
            return True
    return False
