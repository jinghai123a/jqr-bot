#!/usr/bin/env python3

"""

从 VMOS Cloud API 拉取最新 SSH/ADB 凭证，更新 config/tunnel-*.env 并重连隧道。



用法:

  cd /home/bot/55chat-bot

  python3 scripts/vmos-refresh-tunnels.py              # 仅更新 env

  python3 scripts/vmos-refresh-tunnels.py --reconnect    # 更新 + 重连 ADB

  python3 scripts/vmos-refresh-tunnels.py --status       # 查看 EXPIRE_TIME / 建议刷新时刻

  python3 scripts/vmos-refresh-tunnels.py --maintenance-auto   # cron 维护窗全自动：续期+验通+重试

  python3 scripts/vmos-refresh-tunnels.py --maintenance-auto --retry-only  # 19:20 仅失败时续期

  python3 scripts/vmos-refresh-tunnels.py --expire-if-needed [--reconnect]  # 仅 W49 手动紧急，禁止 cron

  python3 scripts/vmos-refresh-tunnels.py --list         # 列出账号下云机

"""

from __future__ import annotations



import argparse

import json

import os

import sys

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _bootstrap_env() -> None:
    from bot_tunnel.env_io import load_env_file as _load
    for key, val in _load(ROOT / "config" / "bot-start.env").items():
        os.environ.setdefault(key, val)


_bootstrap_env()



from bot_tunnel import (  # noqa: E402

    acquire_refresh_lock,

    load_env_file,

    reconnect_sides,

    refresh_side_credentials,

    resolve_pad_code,

)

from bot_tunnel.expire_schedule import (  # noqa: E402

    adb_expire_minutes,

    format_expire_status,

    in_maintenance_window,

    maintenance_window_end_hhmm,

    maintenance_window_start_hhmm,

    print_expire_status_table,

    refresh_buffer_minutes,

    should_refresh_urgent,

)

from bot_tunnel.post_refresh import verify_dual_tunnels

from vmos_api_client import VmosApiClient  # noqa: E402


def _build_sides(root: Path, side_filter: str) -> dict:

    pads_cfg_path = root / "config" / "vmos-pads.json"

    pads_cfg = json.loads(pads_cfg_path.read_text(encoding="utf-8")) if pads_cfg_path.exists() else {}

    bot_env = load_env_file(root / "config" / "bot-start.env")

    all_sides = {

        "right": {

            **(pads_cfg.get("right") or {}),

            "local_port": bot_env.get("BOT_LISTENER_ADB_PORT", "58433"),

            "tunnel_file": root / "config" / "tunnel-right.env",

        },

        "left": {

            **(pads_cfg.get("left") or {}),

            "local_port": bot_env.get("BOT_CLICKER_ADB_PORT", "52840"),

            "tunnel_file": root / "config" / "tunnel-left.env",

        },

    }

    if side_filter == "all":

        return all_sides

    return {side_filter: all_sides[side_filter]}





def _cmd_status(sides: dict) -> int:

    rows = []

    for side, cfg in sides.items():

        code = str(cfg.get("pad_code") or "")

        rows.append(format_expire_status(side, cfg["tunnel_file"], pad_code=code))

    print_expire_status_table(rows)

    print(

        f"[config] expireMinutes={adb_expire_minutes()} "

        f"refresh_buffer_min={refresh_buffer_minutes()} "

        f"maintenance_window="

        f"{maintenance_window_start_hhmm()[0]:02d}:{maintenance_window_start_hhmm()[1]:02d}-"

        f"{maintenance_window_end_hhmm()[0]:02d}:{maintenance_window_end_hhmm()[1]:02d} Beijing "

        f"(OpenAPI padApi/adb expireMinutes 1440~10080)"

    )

    return 0





def _sides_needing_refresh(sides: dict) -> dict:

    out: dict = {}

    for side, cfg in sides.items():

        env = load_env_file(cfg["tunnel_file"])

        if should_refresh_urgent(env):

            out[side] = cfg

            print(f"[expire-if-needed] {side} URGENT refresh (port {cfg['local_port']})")

        else:

            left = format_expire_status(side, cfg["tunnel_file"])

            print(

                f"[expire-if-needed] {side} defer to maintenance left_min={left['minutes_left']} "

                f"next_maint={left.get('next_maintenance_beijing')}"

            )

    return out


def _discover_pads(client: VmosApiClient, refresh_sides: dict) -> tuple[list[dict], dict[str, dict]]:
    need_discover = any(not (cfg.get("pad_code") or "").strip() for cfg in refresh_sides.values())
    pads: list[dict] = []
    models: dict[str, dict] = {}
    if need_discover:
        pads = client.list_pads(page=1, rows=50)
        pad_codes = [str(p.get("padCode") or "") for p in pads if p.get("padCode")]
        models = {str(m.get("padCode")): m for m in client.model_info(pad_codes)}
    return pads, models


def _run_openapi_refresh(
    refresh_sides: dict,
    client: VmosApiClient,
    pads: list,
    models: dict,
) -> list[str]:
    side_failures: list[str] = []
    for side, cfg in refresh_sides.items():
        code = resolve_pad_code(side, cfg, pads, models)
        print(f"[{side}] padCode={code} -> port {cfg['local_port']} expireMinutes={adb_expire_minutes()}")
    for side, cfg in refresh_sides.items():
        _ok, failure = refresh_side_credentials(side, cfg, client, pads, models)
        if failure:
            side_failures.append(failure)
    reconnect_sides(refresh_sides, ROOT)
    return side_failures


def main() -> int:

    parser = argparse.ArgumentParser()

    parser.add_argument("--reconnect", action="store_true", help="更新 env 后执行 reconnect-dual-adb.sh")

    parser.add_argument("--status", action="store_true", help="仅打印凭证过期时间与建议刷新时刻")

    parser.add_argument(
        "--maintenance-auto",
        action="store_true",
        help="维护窗全自动：OpenAPI 续期 + reconnect + 双端验通；失败自动再续一轮",
    )
    parser.add_argument(
        "--retry-only",
        action="store_true",
        help="配合 --maintenance-auto：仅当验通失败时才续期（供 19:20 cron）",
    )
    parser.add_argument(
        "--maintenance-refresh",
        action="store_true",
        help="仅在北京维护窗 BOT_VMOS_MAINTENANCE_START~END（默认 19:00-19:30）执行全量续期",
    )

    parser.add_argument(

        "--expire-if-needed",

        action="store_true",

        help="仅当维护窗前将过期（urgent）时才调用 OpenAPI 刷新；禁止写入 cron，见固定文档 §0",

    )

    parser.add_argument("--list", action="store_true", help="仅列出云机")

    parser.add_argument("--side", choices=("all", "right", "left"), default="all", help="只刷新指定侧")

    args = parser.parse_args()



    sides = _build_sides(ROOT, args.side)



    if args.status:

        return _cmd_status(sides)



    lock_fp = acquire_refresh_lock(ROOT)

    if lock_fp is None:

        print("[skip] another vmos-refresh-tunnels.py is running")

        return 0



    api_env = load_env_file(ROOT / "config" / "vmos-api.env")

    ak = api_env.get("VMOS_ACCESS_KEY") or api_env.get("VMOS_AK")

    sk = api_env.get("VMOS_SECRET_KEY") or api_env.get("VMOS_SK")

    if not ak or not sk:

        print("缺少 config/vmos-api.env (VMOS_ACCESS_KEY / VMOS_SECRET_KEY)", file=sys.stderr)

        os.close(lock_fp)

        return 1



    client = VmosApiClient(ak, sk)



    pads_cfg_path = ROOT / "config" / "vmos-pads.json"

    pads_cfg = json.loads(pads_cfg_path.read_text(encoding="utf-8")) if pads_cfg_path.exists() else {}



    if args.list:

        pads = client.list_pads(page=1, rows=50)

        pad_codes = [str(p.get("padCode") or "") for p in pads if p.get("padCode")]

        models = {str(m.get("padCode")): m for m in client.model_info(pad_codes)}

        print(json.dumps({"pads": pads, "models": models}, ensure_ascii=False, indent=2))

        os.close(lock_fp)

        return 0



    refresh_sides = sides
    pads, models = _discover_pads(client, refresh_sides)

    if args.maintenance_auto:
        if not in_maintenance_window():
            sh, sm = maintenance_window_start_hhmm()
            eh, em = maintenance_window_end_hhmm()
            print(
                f"[maintenance-auto] skip — outside Beijing window "
                f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"
            )
            os.close(lock_fp)
            return 0
        print("[maintenance-auto] pre-check EXPIRE_TIME / tunnel state")
        _cmd_status(sides)
        if args.retry_only:
            ok_pre, pre_out = verify_dual_tunnels(ROOT)
            print(pre_out)
            if ok_pre:
                print("[maintenance-auto] retry-only: tunnels OK — skip API refresh")
                os.close(lock_fp)
                return 0
            print("[maintenance-auto] retry-only: verify failed — renewing credentials")
        else:
            print("[maintenance-auto] scheduled refresh — renew credentials (EXPIRE_TIME will update)")
        side_failures: list[str] = []
        for attempt in (1, 2):
            print(f"[maintenance-auto] refresh+verify attempt {attempt}")
            side_failures = _run_openapi_refresh(refresh_sides, client, pads, models)
            ok_v, vout = verify_dual_tunnels(ROOT)
            print(vout)
            if ok_v and not side_failures:
                print("[maintenance-auto] TUNNEL_MAINTENANCE_OK")
                _cmd_status(refresh_sides)
                os.close(lock_fp)
                return 0
            print(f"[maintenance-auto] verify or API partial fail attempt={attempt}")
        print("[maintenance-auto] TUNNEL_MAINTENANCE_FAIL")
        _cmd_status(refresh_sides)
        os.close(lock_fp)
        return 1

    if args.maintenance_refresh:

        if not in_maintenance_window():

            sh, sm = maintenance_window_start_hhmm()

            eh, em = maintenance_window_end_hhmm()

            print(

                f"[maintenance-refresh] skip — outside Beijing window "

                f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"

            )

            os.close(lock_fp)

            return 0

        print("[maintenance-refresh] in maintenance window — full OpenAPI refresh")

    elif args.expire_if_needed:

        refresh_sides = _sides_needing_refresh(sides)

        if not refresh_sides:

            print("[expire-if-needed] no urgent side — deferred to maintenance window")

            os.close(lock_fp)

            return 0



    need_discover = any(not (cfg.get("pad_code") or "").strip() for cfg in refresh_sides.values())
    if need_discover and not pads:
        pads, models = _discover_pads(client, refresh_sides)

    for side, cfg in refresh_sides.items():

        code = resolve_pad_code(side, cfg, pads, models)

        print(f"[{side}] padCode={code} -> port {cfg['local_port']} expireMinutes={adb_expire_minutes()}")



    side_failures: list[str] = []

    for side, cfg in refresh_sides.items():

        ok, failure = refresh_side_credentials(side, cfg, client, pads, models)

        if failure:

            side_failures.append(failure)



    if args.reconnect or args.expire_if_needed or args.maintenance_refresh:

        reconnect_sides(refresh_sides, ROOT)



    _cmd_status(refresh_sides)



    callback = api_env.get("VMOS_CALLBACK_URL") or ""

    panel_ok = "127.0.0.1:3000" in callback or "195.114.193.237:3000" in callback

    if callback:

        print(f"[callback] VMOS_CALLBACK_URL={callback} panel_ref_ok={panel_ok}")

    else:

        print("[warn] config/vmos-api.env 缺少 VMOS_CALLBACK_URL → Panel :3000/api/vmos/callback")



    if side_failures and len(side_failures) == len(refresh_sides):

        os.close(lock_fp)

        return 1

    if side_failures:

        print(f"[warn] partial refresh failures: {side_failures}")

    os.close(lock_fp)

    return 0





if __name__ == "__main__":

    raise SystemExit(main())

