#!/usr/bin/env python3
"""本机 VMOS SSH 隧道 + 隔离 ADB（不经过 VPS）。"""
from __future__ import annotations

import re
import select
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import _parse_env_file  # noqa: WPS433
from bot_tunnel.adb_probe import adb_probe_port

_TUNNEL_THREADS: list[threading.Thread] = []


class _ForwardHandler(socketserver.BaseRequestHandler):
    chain_host: str = "localhost"
    chain_port: int = 1
    ssh_transport: object = None

    def handle(self) -> None:
        try:
            chan = self.ssh_transport.open_channel(  # type: ignore[attr-defined]
                "direct-tcpip",
                (self.chain_host, self.chain_port),
                self.request.getpeername(),
            )
        except Exception:
            return
        if chan is None:
            return
        try:
            while True:
                r, _, _ = select.select([self.request, chan], [], [], 1.0)
                if self.request in r:
                    data = self.request.recv(1024)
                    if not data:
                        break
                    chan.send(data)
                if chan in r:
                    data = chan.recv(1024)
                    if not data:
                        break
                    self.request.send(data)
        finally:
            chan.close()
            self.request.close()


def _parse_forward(ssh_command: str) -> tuple[int, str, int]:
    m = re.search(r"-L\s+(\d+):([^:]+):(\d+)", ssh_command)
    if not m:
        raise ValueError(f"no -L forward in: {ssh_command!r}")
    return int(m.group(1)), m.group(2), int(m.group(3))


def _start_paramiko_tunnel(ssh_command: str, password: str) -> None:
    import paramiko

    from bot_tunnel.ssh_parse import parse_ssh_command

    host, port, user = parse_ssh_command(ssh_command)
    local_port, chain_host, chain_port = _parse_forward(ssh_command)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=int(port), username=user, password=password, timeout=30)
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("paramiko transport missing")

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    handler = type(
        "H",
        (_ForwardHandler,),
        {"chain_host": chain_host, "chain_port": chain_port, "ssh_transport": transport},
    )
    server = Server(("127.0.0.1", local_port), handler)

    def _serve() -> None:
        server.serve_forever()

    th = threading.Thread(target=_serve, daemon=True)
    th.start()
    _TUNNEL_THREADS.append(th)
    time.sleep(1.5)
    print(f"tunnel OK {user}@{host}:{port} -> 127.0.0.1:{local_port} -> {chain_host}:{chain_port}")


def _load_tunnel(side: str) -> dict[str, str]:
    name = "tunnel-right.env" if side == "right" else "tunnel-left.env"
    return _parse_env_file(ROOT / "config" / name)


def connect_side(side: str) -> bool:
    cfg = _load_tunnel(side)
    ssh_cmd = cfg.get("VMOS_SSH_COMMAND", "").strip()
    adb_cmd = cfg.get("VMOS_ADB_COMMAND", "").strip()
    password = cfg.get("SSH_PASS", "").strip()
    port = str(cfg.get("LOCAL_PORT", "58433" if side == "right" else "52840"))
    if not ssh_cmd or not password:
        print(f"[{side}] missing VMOS_SSH_COMMAND or SSH_PASS in config/tunnel-*.env")
        return False
    if not adb_probe_port(port):
        _start_paramiko_tunnel(ssh_cmd, password)
    else:
        print(f"[{side}] adb already OK :{port}")
    if adb_cmd:
        subprocess.run(adb_cmd, shell=True, check=False, timeout=30)
    else:
        subprocess.run(["adb", "connect", f"127.0.0.1:{port}"], check=False, timeout=20)
    ok = adb_probe_port(port)
    if not ok:
        time.sleep(2)
        if adb_cmd:
            subprocess.run(adb_cmd, shell=True, check=False, timeout=30)
        else:
            subprocess.run(["adb", "connect", f"127.0.0.1:{port}"], check=False, timeout=20)
        ok = adb_probe_port(port)
    print(f"[{side}] probe :{port} -> {'OK' if ok else 'FAIL'}")
    return ok


def connect_isolated_adb() -> None:
    right_cfg = _load_tunnel("right")
    left_cfg = _load_tunnel("left")
    lport = left_cfg.get("LOCAL_PORT") or "52840"
    rport = right_cfg.get("LOCAL_PORT") or "58433"
    env = _parse_env_file(ROOT / "config" / "bot-start.env")
    lserver = env.get("BOT_CLICKER_ADB_SERVER_PORT", "5039")
    rserver = env.get("BOT_LISTENER_ADB_SERVER_PORT", "5038")
    for srv, port in ((lserver, lport), (rserver, rport)):
        subprocess.run(
            ["adb", "-P", srv, "connect", f"127.0.0.1:{port}"],
            check=False,
            timeout=15,
        )
        subprocess.run(
            ["adb", "-P", srv, "-s", f"127.0.0.1:{port}", "shell", "echo", f"OK_{port}"],
            check=False,
            timeout=15,
        )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", action="store_true", help="保持隧道进程不退出")
    args = ap.parse_args()
    ok_r = connect_side("right")
    ok_l = connect_side("left")
    connect_isolated_adb()
    code = 0 if ok_r and ok_l else 1
    if args.hold and code == 0:
        print("tunnels holding — Ctrl+C to stop", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
