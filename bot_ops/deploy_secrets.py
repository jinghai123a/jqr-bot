"""Deploy-time secret injection: read local gitignored env, push to VPS."""
from __future__ import annotations

from pathlib import Path

from bot_ops.ssh_client import VpsSSH

# Never commit these; examples hold placeholders only.
RUNTIME_SECRET_FILES = (
    "config/vmos-api.env",
    "config/tunnel-left.env",
    "config/tunnel-right.env",
)

_SECRET_KEYS = frozenset(
    {
        "SSH_PASS",
        "VMOS_ACCESS_KEY",
        "VMOS_SECRET_KEY",
        "VPS_PASSWORD",
        "RIGHT_SSH_PASS",
        "LEFT_SSH_PASS",
    }
)


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def local_secrets_ready(root: Path) -> tuple[bool, list[str]]:
    """Return (all_ok, missing_descriptions)."""
    missing: list[str] = []
    for rel in RUNTIME_SECRET_FILES:
        path = root / rel
        if not path.is_file():
            missing.append(f"{rel} (file missing — copy from .example)")
            continue
        env = _parse_env(path)
        if rel.endswith("tunnel-left.env") or rel.endswith("tunnel-right.env"):
            if not env.get("SSH_PASS", "").strip():
                missing.append(f"{rel}: SSH_PASS empty")
        if rel.endswith("vmos-api.env"):
            if not env.get("VMOS_ACCESS_KEY", "").strip():
                missing.append(f"{rel}: VMOS_ACCESS_KEY empty")
            if not env.get("VMOS_SECRET_KEY", "").strip():
                missing.append(f"{rel}: VMOS_SECRET_KEY empty")
    return (not missing, missing)


def push_runtime_secrets(ssh: VpsSSH, root: Path, remote_root: str) -> list[str]:
    """Upload local secret env files that exist and have required keys filled."""
    pushed: list[str] = []
    for rel in RUNTIME_SECRET_FILES:
        local = root / rel
        if not local.is_file():
            continue
        env = _parse_env(local)
        if rel.endswith("vmos-api.env"):
            if not env.get("VMOS_ACCESS_KEY") or not env.get("VMOS_SECRET_KEY"):
                continue
        if rel.endswith(".env") and "tunnel" in rel:
            if not env.get("SSH_PASS"):
                continue
        remote = f"{remote_root}/{rel.replace(chr(92), '/')}"
        ssh.sftp_put(str(local), remote)
        ssh.run(f"chmod 600 {remote} 2>/dev/null; echo pushed_{rel.split('/')[-1]}", 8)
        pushed.append(rel)
    return pushed
