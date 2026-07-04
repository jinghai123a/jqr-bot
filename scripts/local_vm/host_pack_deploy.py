#!/usr/bin/env python3
"""VM 打包 + 下载到宿主机 + 可选一键部署 APS。"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

def load_vm_config() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location(
        "host_deploy", ROOT / "scripts" / "local_vm" / "host_deploy.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("host_deploy missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_vm_config()


def ssh_client(cfg):
    spec = importlib.util.spec_from_file_location(
        "host_deploy", ROOT / "scripts" / "local_vm" / "host_deploy.py",
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.ssh_client(cfg)


def run_ssh(client, cmd: str, timeout: int = 300) -> str:
    spec = importlib.util.spec_from_file_location(
        "host_deploy", ROOT / "scripts" / "local_vm" / "host_deploy.py",
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.run_ssh(client, cmd, timeout)

LAB = "/opt/55m-lab"
APP = f"{LAB}/app"
HOST_REL = ROOT / "artifacts" / "55m-releases"


def pack_on_vm(client) -> str:
    out = run_ssh(
        client,
        f"sudo -u bot LAB_ROOT={LAB} bash {APP}/scripts/local_vm/pack_55m_release.sh",
        600,
    )
    print(out)
    for line in out.splitlines():
        if line.startswith("PACK_OK "):
            return line.split("PACK_OK ", 1)[1].strip()
    latest = run_ssh(client, f"readlink -f {LAB}/releases/55m-latest.tar.gz 2>/dev/null || true", 30).strip()
    if latest:
        return latest
    raise RuntimeError("pack failed — no tarball path")


def download_bundle(client, remote_tar: str) -> Path:
    HOST_REL.mkdir(parents=True, exist_ok=True)
    name = Path(remote_tar).name
    local = HOST_REL / name
    sftp = client.open_sftp()
    sftp.get(remote_tar, str(local))
    sftp.close()
    (HOST_REL / "55m-latest.tar.gz").unlink(missing_ok=True)
    try:
        (HOST_REL / "55m-latest.tar.gz").symlink_to(local.name)
    except OSError:
        import shutil
        shutil.copy2(local, HOST_REL / "55m-latest.tar.gz")
    print(f"DOWNLOAD_OK {local}")
    return local


def deploy_aps(local_tar: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("edge_auto_all", ROOT / "scripts" / "edge_auto_all.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("edge_auto_all missing")
    from bot_ops.config import load_vps_config
    from bot_ops.ssh_client import VpsSSH

    aps = "/home/bot/55chat-bot"
    cfg = load_vps_config(ROOT)
    remote_tar = f"/tmp/{local_tar.name}"
    with VpsSSH(cfg) as ssh:
        ssh.sftp_put(str(local_tar), remote_tar)
        unpack = f"{aps}/scripts/local_vm/guest_aps_unpack.sh"
        print(ssh.run(f"test -x {unpack} || chmod +x {unpack} 2>/dev/null; bash {unpack} {remote_tar}", 600))
        print(ssh.run(f"curl -sf http://127.0.0.1:8790/health; echo", 20))
    print("APS_DEPLOY_FROM_BUNDLE_OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", action="store_true", help="VM 内打包并下载到 artifacts/55m-releases")
    ap.add_argument("--deploy-aps", action="store_true", help="用最新包部署 APS")
    args = ap.parse_args()
    if not args.pack and not args.deploy_aps:
        args.pack = True

    cfg = load_vm_config()
    local_tar: Path | None = None
    if args.pack:
        with ssh_client(cfg) as client:
            remote = pack_on_vm(client)
            local_tar = download_bundle(client, remote)

    if args.deploy_aps:
        tar = local_tar or (HOST_REL / "55m-latest.tar.gz")
        if not tar.is_file():
            raise SystemExit(f"no bundle: {tar}")
        deploy_aps(tar.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
