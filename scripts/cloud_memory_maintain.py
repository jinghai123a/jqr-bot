#!/usr/bin/env python3



"""云集 + VPS 内存维护（默认走铁律7 daily_cycle；--use-tunnel 才占 ADB）。"""



from __future__ import annotations



import argparse

import json

import sys

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))





def main() -> int:

    p = argparse.ArgumentParser()

    p.add_argument("--purge-apps", action="store_true", help="卸载非白名单第三方 App（APS）")

    p.add_argument("--dry-run", action="store_true")

    p.add_argument(

        "--use-tunnel",

        action="store_true",

        help="紧急：经 ADB 隧道 trim（日常禁止，用 daily_memory_cycle）",

    )

    p.add_argument(

        "--daily",

        action="store_true",

        help="等同 scripts/daily_memory_cycle.py",

    )

    args = p.parse_args()



    if args.daily or not args.use_tunnel:

        from bot_ops.daily_memory_cycle import run_daily_memory_cycle

        from bot_ops.runtime import apply_bot_start_env



        apply_bot_start_env(ROOT)

        report = run_daily_memory_cycle(ROOT)

        if args.purge_apps:

            from bot_ops.app_purge import purge_both



            report["aps"] = purge_both(ROOT, dry_run=args.dry_run)

        print(json.dumps(report, ensure_ascii=False, indent=2))

        return 0



    from bot_ops.cloud_memory_clean import trim_both_cloud_phones, vmos_clean_app_home



    report: dict = {"phase": "cloud_memory_maintain_tunnel", "warning": "uses_adb_tunnel"}

    report["adb_trim"] = trim_both_cloud_phones(ROOT)

    report["vmos"] = vmos_clean_app_home(ROOT)

    try:

        from bot_ops.ephemeral_burn import burn_vps_ephemeral



        report["ephemeral_burn"] = burn_vps_ephemeral(ROOT)

    except Exception as ex:

        report["ephemeral_burn"] = {"error": str(ex)}

    if args.purge_apps:

        from bot_ops.app_purge import purge_both



        report["aps"] = purge_both(ROOT, dry_run=args.dry_run)

    print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0





if __name__ == "__main__":

    raise SystemExit(main())

