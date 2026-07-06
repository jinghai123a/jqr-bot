#!/usr/bin/env python3

"""

L3 双进程监督器 — 只监督 LISTENER/CLICKER 子进程生死，不碰 ADB/隧道。

隧道自愈交给 cron：vmos-dual-watchdog + vmos-refresh + reconnect-dual-adb（运维手册 §5/§7）。

"""

from __future__ import annotations



import multiprocessing as mp

import os

import sys

import time

from pathlib import Path



ROOT = Path(__file__).resolve().parent

R = os.environ.get("BOT_ROOT", str(ROOT))





def _child_env(role: str) -> dict[str, str]:

    env = dict(os.environ)

    for stale in (
        "BOT_LISTENER_ADB_PORT",
        "BOT_CLICKER_ADB_PORT",
        "BOT_CLICKER_ID",
        "BOT_CLICKER_IDS",
    ):
        env.pop(stale, None)

    env["BOT_ROLE"] = role

    env["BOT_DUAL_PROCESS"] = "1"

    env["BOT_ADB_ISOLATED"] = "1"

    env["BOT_LOCK_FILE"] = f"{R}/data/bot.lock.{role.lower()}"

    env["BOT_LISTENER_ADB_SERVER_PORT"] = "5038"

    env["BOT_CLICKER_ADB_SERVER_PORT"] = "5039"

    if role == "LISTENER":

        env.setdefault("BOT_GATEWAY_ENABLED", "1")

        env.setdefault("BOT_INGRESS_PORT", "8770")

    else:

        env["BOT_GATEWAY_ENABLED"] = "0"

    return env





def _run_role(role: str) -> None:

    os.chdir(R)

    sys.path.insert(0, R)

    os.environ.update(_child_env(role))

    from bot_ops.runtime import apply_bot_start_env



    apply_bot_start_env(Path(R))

    os.environ["BOT_ROLE"] = role

    from bot_ops.adb_isolated import ensure_adb_servers

    from bot_ops.sqlite_wal import enable_wal_tree



    ensure_adb_servers()

    enable_wal_tree(Path(R))

    import bot_55chat_daemon as d



    d.main()





def main() -> int:
    if os.environ.get("BOT_EXECUTOR", "adb").lower() == "ws":
        print(
            "[dual-supervisor] BOT_EXECUTOR=ws — 桌面 WS 栈已接管群聊 OUT，禁止启动 ADB 双进程。"
            " 请运行 scripts/desktop_local_stack.py 或 unset BOT_EXECUTOR。",
            flush=True,
        )
        return 2

    from bot_ops.process_hygiene import (

        disable_patrol_systemd,

        purge_legacy_patrol,

        purge_orphan_daemon_children,

        purge_stray_standalone_daemon,

    )

    from bot_ops.runtime import apply_bot_start_env



    apply_bot_start_env(ROOT)

    listener_optional = os.environ.get("BOT_LISTENER_OPTIONAL", "0").lower() in (
        "1",
        "true",
        "yes",
    )
    spawn_roles = ("CLICKER",) if listener_optional else ("LISTENER", "CLICKER")

    disable_patrol_systemd()

    purge_legacy_patrol()

    purge_stray_standalone_daemon()

    purge_orphan_daemon_children()

    mp.set_start_method("spawn", force=True)

    py = os.environ.get("BOT_PYTHON") or f"{R}/.venv/bin/python3"

    if not os.path.isfile(py):

        py = sys.executable

    if os.environ.get("BOT_GATEWAY_ENABLED", "1") == "1":

        import subprocess



        subprocess.run(["pkill", "-f", "mock_gateway.py"], check=False)

        subprocess.Popen(

            [py, f"{R}/mock_gateway.py"],

            cwd=R,

            stdout=open(f"{R}/logs/gateway.log", "a"),

            stderr=subprocess.STDOUT,

        )

        time.sleep(1)



    print(
        f"[dual-supervisor] root={R} spawning {','.join(spawn_roles)} "
        f"(listener_optional={listener_optional})",
        flush=True,
    )

    procs: list[mp.Process] = []

    last_stray_purge = 0.0

    for role in spawn_roles:

        p = mp.Process(target=_run_role, args=(role,), name=f"bot-{role.lower()}", daemon=False)

        p.start()

        procs.append(p)

        print(f"[dual-supervisor] {role} pid={p.pid}", flush=True)

        time.sleep(3)



    while True:

        now = time.time()

        if now - last_stray_purge >= 120:

            try:

                from bot_ops.process_hygiene import purge_stray_standalone_daemon



                n = purge_stray_standalone_daemon()

                if n:

                    print(f"[dual-supervisor] killed stray standalone n={n}", flush=True)

            except Exception:

                pass

            last_stray_purge = now

        for i, p in enumerate(procs):

            if not p.is_alive():

                print(f"[dual-supervisor] {p.name} died exit={p.exitcode} — respawn", flush=True)

                try:

                    p.join(timeout=5)

                except Exception:

                    pass

                role = p.name.split("-")[-1].upper()

                if listener_optional and role == "LISTENER":
                    print(
                        "[dual-supervisor] skip LISTENER respawn (BOT_LISTENER_OPTIONAL=1)",
                        flush=True,
                    )
                    continue

                np = mp.Process(target=_run_role, args=(role,), name=p.name, daemon=False)

                np.start()

                procs[i] = np

                print(f"[dual-supervisor] respawned {role} pid={np.pid}", flush=True)

        time.sleep(10)





if __name__ == "__main__":

    raise SystemExit(main())

