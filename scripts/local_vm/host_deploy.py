#!/usr/bin/env python3
"""宿主机 → VMware：全量同步 55M 到 /opt/55m-lab/app。"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bot_ops.config import _parse_env_file

# 全量同步：仅剔除垃圾目录；vendor / probe-android / docs 全部进 VM
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".gradle",
    "build",
    ".cursor",
}
SKIP_SUFFIX = {".pyc", ".pyo"}
KEEP_CONFIG = {
    "bot-start.env",
    "tunnel-left.env",
    "tunnel-right.env",
    "vmos-api.env",
    "pinned-coords.json",
    "local-vm.env",
    "local-vm.env.example",
}


def load_vm_config() -> dict[str, str]:
    path = ROOT / "config" / "local-vm.env"
    if not path.is_file():
        path = ROOT / "config" / "local-vm.env.example"
    cfg = _parse_env_file(path)
    cfg.setdefault("VM_55M_ROOT", "/opt/55m-lab")
    cfg.setdefault("VM_BOT_ROOT", "/opt/55m-lab/app")
    cfg.setdefault("VM_USER", "bot")
    cfg.setdefault("VM_SSH_PORT", "22")
    return cfg


def ssh_client(cfg: dict[str, str]):
    import paramiko

    host = cfg.get("VM_HOST", "").strip()
    if not host:
        raise RuntimeError("请配置 config/local-vm.env 的 VM_HOST")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw: dict = {
        "hostname": host,
        "port": int(cfg.get("VM_SSH_PORT", "22")),
        "username": cfg.get("VM_USER", "bot"),
        "timeout": 30,
    }
    key = cfg.get("VM_SSH_KEY_PATH", "").strip()
    if key:
        kw["key_filename"] = key
    else:
        pw = cfg.get("VM_PASSWORD", "").strip()
        if not pw:
            raise RuntimeError("VM_PASSWORD 或 VM_SSH_KEY_PATH 必填")
        kw["password"] = pw
    client.connect(**kw)
    return client


def run_ssh(client, cmd: str, timeout: int = 300) -> str:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode("utf-8", "replace")


def should_skip(rel: Path) -> bool:
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    if rel.suffix in SKIP_SUFFIX:
        return True
    if rel.parts and rel.parts[0] == "config" and rel.name.endswith(".env"):
        if rel.name not in KEEP_CONFIG and "example" not in rel.name:
            return True
    if "artifacts" in rel.parts and rel.suffix == ".tar.gz":
        return True
    return False


def iter_upload_files() -> list[Path]:
    return [p for p in ROOT.rglob("*") if p.is_file() and not should_skip(p.relative_to(ROOT))]


def sync_project(client, app_root: str, lab_root: str) -> None:
    sftp = client.open_sftp()

    def mkdir_p(remote: str) -> None:
        parts = remote.strip("/").split("/")
        cur = ""
        for part in parts:
            cur += f"/{part}"
            try:
                sftp.stat(cur)
            except OSError:
                try:
                    sftp.mkdir(cur)
                except OSError:
                    pass

    pw = load_vm_config().get("VM_PASSWORD", "")
    user = load_vm_config().get("VM_USER", "bot")
    sudo = f"echo '{pw}' | sudo -S " if pw else "sudo "
    run_ssh(client, f"{sudo}mkdir -p {lab_root}/{{app,data,logs,artifacts,releases}} && "
            f"{sudo}chown -R {user}:{user} {lab_root}")

    files = iter_upload_files()
    print(f"full sync {len(files)} files -> {app_root}")
    for local in files:
        rel = local.relative_to(ROOT).as_posix()
        remote = f"{app_root}/{rel}"
        mkdir_p(str(Path(remote).parent.as_posix()))
        sftp.put(str(local), remote)
    sftp.close()
    sh_fix = (
        f"find {app_root}/scripts -name '*.sh' -exec sed -i 's/\\r$//' {{}} + 2>/dev/null; "
        f"chmod +x {app_root}/scripts/*.sh {app_root}/scripts/local_vm/*.sh 2>/dev/null; true"
    )
    run_ssh(client, sh_fix)
    # 知识库镜像到专区根（便于 VM 内速查）
    run_ssh(
        client,
        f"mkdir -p {lab_root}/knowledge && "
        f"cp -a {app_root}/config/55m-knowledge/* {lab_root}/knowledge/ 2>/dev/null || true",
    )


def bootstrap(client, lab_root: str, app_root: str) -> None:
    user = load_vm_config().get("VM_USER", "bot")
    pw = load_vm_config().get("VM_PASSWORD", "")
    sudo = f"echo '{pw}' | sudo -S " if pw else "sudo "
    print(run_ssh(
        client,
        f"{sudo}LAB_ROOT={lab_root} APP_ROOT={app_root} BOT_USER={user} "
        f"bash {app_root}/scripts/local_vm/guest_bootstrap.sh",
        900,
    ))


def edge_up(client, lab_root: str, app_root: str) -> None:
    print(run_ssh(
        client,
        f"sudo -u bot LAB_ROOT={lab_root} BOT_ROOT={app_root} bash {app_root}/scripts/local_vm/guest_edge_stack.sh",
        600,
    ))


def parity_from_aps() -> None:
    spec = importlib.util.spec_from_file_location(
        "edge_sync_aps_parity", ROOT / "scripts" / "edge_sync_aps_parity.py",
    )
    if spec is None or spec.loader is None:
        return
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


def main() -> int:
    ap = argparse.ArgumentParser(description="全量部署 55M 到 VM /opt/55m-lab")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--edge-up", action="store_true")
    ap.add_argument("--parity", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if not any((args.sync, args.bootstrap, args.edge_up, args.parity, args.all)):
        args.all = True

    if args.parity or args.all:
        print("=== APS parity (board_capture 等) ===")
        try:
            parity_from_aps()
        except Exception as ex:
            print(f"parity skip: {ex}")

    cfg = load_vm_config()
    lab = cfg.get("VM_55M_ROOT", "/opt/55m-lab")
    app = cfg.get("VM_BOT_ROOT", f"{lab}/app")

    user = cfg.get("VM_USER", "bot")
    with ssh_client(cfg) as client:
        sync_project(client, app, lab)
        if args.sync and not (args.bootstrap or args.edge_up or args.all):
            print("SYNC_OK")
            return 0
        if args.bootstrap or args.all:
            bootstrap(client, lab, app)
        if args.edge_up or args.all:
            print(run_ssh(
                client,
                f"sudo -u {user} LAB_ROOT={lab} BOT_ROOT={app} bash {app}/scripts/local_vm/guest_edge_stack.sh",
                600,
            ))
    print("HOST_DEPLOY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
