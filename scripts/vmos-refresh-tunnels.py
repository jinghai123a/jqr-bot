#!/usr/bin/env python3
"""
从 VMOS Cloud API 拉取最新 SSH/ADB 凭证，更新 config/tunnel-*.env 并重连隧道。

用法:
  cd /home/bot/55chat-bot
  python3 scripts/vmos-refresh-tunnels.py              # 仅更新 env
  python3 scripts/vmos-refresh-tunnels.py --reconnect    # 更新 + 重连 ADB
  python3 scripts/vmos-refresh-tunnels.py --list         # 列出账号下云机
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from vmos_api_client import VmosApiClient  # noqa: E402


def load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def shell_env_line(key: str, value: str) -> str:
    """Write KEY=value for tunnel env; command/adb 字段必须加引号。"""
    if not value:
        return f"{key}="
    if key in ("VMOS_SSH_COMMAND", "VMOS_ADB_COMMAND") or re.search(r"[\s#'\"\\]", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{escaped}"'
    return f"{key}={value}"


def parse_local_port(ssh_command: str, adb_command: str, fallback: str) -> str:
    m = re.search(r"-L\s+(\d+):", ssh_command)
    if m:
        return m.group(1)
    m = re.search(r"localhost:(\d+)", adb_command)
    if m:
        return m.group(1)
    return fallback


def write_tunnel_env(
    path: Path,
    local_port: str,
    ssh_host: str,
    ssh_port: str,
    ssh_user: str,
    ssh_pass: str,
    *,
    ssh_command: str = "",
    adb_command: str = "",
    expire_time: str = "",
) -> None:
    """保存 OpenAPI 返回的 command/adb 原文（禁止改写）。"""
    lines = [
        "# auto-updated by vmos-refresh-tunnels.py — VMOS OpenAPI padApi/adb 原文",
        "# 文档: https://cloud.vmoscloud.com/vmoscloud/doc/zh/server/OpenAPI.html",
        shell_env_line("LOCAL_PORT", local_port),
        shell_env_line("VMOS_SSH_COMMAND", ssh_command.strip()),
        shell_env_line("VMOS_ADB_COMMAND", adb_command.strip()),
        shell_env_line("SSH_HOST", ssh_host),
        shell_env_line("SSH_PORT", ssh_port),
        shell_env_line("SSH_USER", ssh_user),
        shell_env_line("SSH_PASS", ssh_pass),
        shell_env_line("EXPIRE_TIME", expire_time),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def parse_ssh_command(command: str) -> tuple[str, str, str]:
    """从 VMOS 返回的 SSH command 解析 host/port/user（仅用于日志/校验）。"""
    port_m = re.search(r"-p\s+(\d+)", command)
    user_host_m = re.search(r"([\w-]+)@([\d.]+)", command)
    if not user_host_m:
        raise ValueError(f"无法解析 SSH command: {command!r}")
    user = user_host_m.group(1)
    host = user_host_m.group(2)
    port = port_m.group(1) if port_m else "1824"
    return host, port, user


def android_major(rom_version: str | int | None) -> int | None:
    if rom_version is None:
        return None
    s = str(rom_version)
    m = re.match(r"(\d+)", s)
    return int(m.group(1)) if m else None


def resolve_pad_code(side: str, cfg: dict, client: VmosApiClient, pads: list[dict], models: dict[str, dict]) -> str:
    explicit = (cfg.get("pad_code") or "").strip()
    if explicit:
        return explicit

    want_android = cfg.get("match_android")
    want_ip = (cfg.get("match_egress_ip") or "").strip()

    candidates: list[tuple[dict, dict]] = []
    for pad in pads:
        code = str(pad.get("padCode") or pad.get("pad_code") or "")
        if not code:
            continue
        model = models.get(code, {})
        candidates.append((pad, model))

    def score(item: tuple[dict, dict]) -> tuple[int, str]:
        pad, model = item
        code = str(pad.get("padCode") or "")
        s = 0
        rom = android_major(model.get("romVersion") or model.get("androidVersion"))
        if want_android and rom == int(want_android):
            s += 10
        pad_ip = str(pad.get("padIp") or pad.get("deviceIp") or "")
        if want_ip and want_ip in pad_ip:
            s += 5
        return s, code

    ranked = sorted(candidates, key=score, reverse=True)
    if not ranked or score(ranked[0])[0] <= 0:
        raise RuntimeError(
            f"{side}: 未找到匹配云机 (android={want_android}, ip={want_ip})。"
            f"请在 config/vmos-pads.json 填写 pad_code"
        )
    best_score, best_code = score(ranked[0])
    if len(ranked) > 1 and score(ranked[1])[0] == best_score:
        codes = [score(x)[1] for x in ranked if score(x)[0] == best_score]
        raise RuntimeError(f"{side}: 多台云机同分 {codes}，请手动指定 pad_code")
    return best_code


def adb_probe_port(port: str) -> bool:
    for serial in (f"127.0.0.1:{port}", f"localhost:{port}"):
        r = subprocess.run(
            ["adb", "-s", serial, "shell", "echo", "OK"],
            capture_output=True, text=True, timeout=12,
        )
        if r.returncode == 0 and "OK" in (r.stdout or ""):
            return True
    return False


def acquire_refresh_lock() -> int | None:
    lock_path = ROOT / "logs" / ".vmos-refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fp = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fp)
        return None
    return fp


def main() -> int:
    lock_fp = acquire_refresh_lock()
    if lock_fp is None:
        print("[skip] another vmos-refresh-tunnels.py is running")
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconnect", action="store_true", help="更新 env 后执行 reconnect-dual-adb.sh")
    parser.add_argument("--list", action="store_true", help="仅列出云机")
    parser.add_argument("--side", choices=("all", "right", "left"), default="all", help="只刷新指定侧")
    args = parser.parse_args()

    api_env = load_env_file(ROOT / "config" / "vmos-api.env")
    ak = api_env.get("VMOS_ACCESS_KEY") or api_env.get("VMOS_AK")
    sk = api_env.get("VMOS_SECRET_KEY") or api_env.get("VMOS_SK")
    if not ak or not sk:
        print("缺少 config/vmos-api.env (VMOS_ACCESS_KEY / VMOS_SECRET_KEY)", file=sys.stderr)
        return 1

    client = VmosApiClient(ak, sk)

    pads_cfg_path = ROOT / "config" / "vmos-pads.json"
    pads_cfg = json.loads(pads_cfg_path.read_text(encoding="utf-8")) if pads_cfg_path.exists() else {}

    if args.list:
        pads = client.list_pads(page=1, rows=50)
        pad_codes = [str(p.get("padCode") or "") for p in pads if p.get("padCode")]
        models = {str(m.get("padCode")): m for m in client.model_info(pad_codes)}
        print(json.dumps({"pads": pads, "models": models}, ensure_ascii=False, indent=2))
        return 0

    bot_env = load_env_file(ROOT / "config" / "bot-start.env")
    all_sides = {
        "right": {
            **(pads_cfg.get("right") or {}),
            "local_port": bot_env.get("BOT_LISTENER_ADB_PORT", "49868"),
            "tunnel_file": ROOT / "config" / "tunnel-right.env",
        },
        "left": {
            **(pads_cfg.get("left") or {}),
            "local_port": bot_env.get("BOT_CLICKER_ADB_PORT", "63221"),
            "tunnel_file": ROOT / "config" / "tunnel-left.env",
        },
    }
    sides = all_sides if args.side == "all" else {args.side: all_sides[args.side]}

    need_discover = any(not (cfg.get("pad_code") or "").strip() for cfg in sides.values())
    pads: list[dict] = []
    models: dict[str, dict] = {}
    if need_discover:
        pads = client.list_pads(page=1, rows=50)
        pad_codes = [str(p.get("padCode") or "") for p in pads if p.get("padCode")]
        models = {str(m.get("padCode")): m for m in client.model_info(pad_codes)}

    resolved: dict[str, str] = {}
    side_failures: list[str] = []
    for side, cfg in sides.items():
        code = resolve_pad_code(side, cfg, client, pads, models)
        resolved[side] = code
        print(f"[{side}] padCode={code} -> port {cfg['local_port']}")

    for side, cfg in sides.items():
        code = resolved[side]
        port = str(cfg["local_port"])
        last_exc: Exception | None = None
        adb: dict = {}
        for attempt in range(12):
            try:
                if attempt:
                    wait = min(90, 8 * attempt)
                    time.sleep(wait)
                # 官方流程：openOnlineAdb(异步) → taskStatus=3 → get adb
                try:
                    tasks = client.open_adb([code])
                    client.wait_open_adb_tasks(tasks)
                except RuntimeError as exc:
                    print(f"[warn] openOnlineAdb {side}: {exc}")
                adb = client.get_adb(code, enable=True, expire_minutes=10080, retries=3)
                command = str(adb.get("command") or "")
                ssh_pass = str(adb.get("key") or "")
                if not command or not ssh_pass:
                    raise RuntimeError("adb 接口未返回完整 command/key，需先 openOnlineAdb")
                break
            except RuntimeError as exc:
                last_exc = exc
                print(f"[warn] refresh {side} attempt {attempt + 1}: {exc}")
        if not adb:
            if adb_probe_port(port):
                print(f"[{side}] API busy but adb :{port} online — keep existing tunnel env")
                continue
            if cfg["tunnel_file"].exists() and load_env_file(cfg["tunnel_file"]).get("SSH_PASS"):
                print(f"[{side}] API failed — keep existing {cfg['tunnel_file'].name}, will try reconnect")
                side_failures.append(side)
                continue
            print(f"[{side}] FATAL refresh: {last_exc}", file=sys.stderr)
            side_failures.append(side)
            continue
        command = str(adb.get("command") or "")
        adb_cmd = str(adb.get("adb") or "")
        ssh_pass = str(adb.get("key") or "")
        host, ssh_port, user = parse_ssh_command(command)
        api_port = parse_local_port(command, adb_cmd, str(cfg["local_port"]))
        write_tunnel_env(
            cfg["tunnel_file"],
            api_port,
            host,
            ssh_port,
            user,
            ssh_pass,
            ssh_command=command,
            adb_command=adb_cmd,
            expire_time=str(adb.get("expireTime") or ""),
        )
        print(
            f"[{side}] updated {cfg['tunnel_file'].name} "
            f"port={api_port} host={host}:{ssh_port} expire={adb.get('expireTime')}"
        )

    if args.reconnect:
        for side, cfg in sides.items():
            port = str(cfg["local_port"])
            if adb_probe_port(port):
                continue
            script = "tunnel-right.sh" if side == "right" else "tunnel-left.sh"
            print(f"[reconnect] {side} via {script}")
            r = subprocess.run(
                ["bash", str(ROOT / "scripts" / script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=90,
            )
            print(r.stdout.strip() or r.stderr.strip())
        subprocess.run(["adb", "devices", "-l"], check=False)

    if side_failures and len(side_failures) == len(sides):
        os.close(lock_fp)
        return 1
    if side_failures:
        print(f"[warn] partial refresh failures: {side_failures}")
    os.close(lock_fp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
