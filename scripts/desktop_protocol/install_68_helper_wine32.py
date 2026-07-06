#!/usr/bin/env python3

"""VPS: deploy 68-helper by extracting NSIS app-64.7z (bypass Wine installer Retry loop)."""

from __future__ import annotations



import os

import sys

from pathlib import Path



ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config

from bot_ops.ssh_client import VpsSSH



BOT_SCRIPT = r"""#!/bin/bash

set -e

export WINEARCH=win64

export WINEPREFIX=/home/bot/.wine68helper

export DISPLAY=:0

INSTALLER=/opt/55chat/68-helper-26.7.4-setup-win-x64.exe

NSIS_EXTRACT=/opt/55chat/68-helper-extract

APP=/opt/55chat/68-helper-app

DEST="$WINEPREFIX/drive_c/Program Files/68-helper"



# kill GUI installer only (never pkill -f '68-helper' — matches ssh cmdline)

for pid in $(pgrep -f setup-win-x64.exe); do kill "$pid" 2>/dev/null || true; done

wineserver -k 2>/dev/null || true

sleep 1



if [ ! -f "$INSTALLER" ]; then

  echo "missing $INSTALLER"

  exit 1

fi



if [ ! -f "$NSIS_EXTRACT/\$PLUGINSDIR/app-64.7z" ]; then

  echo "extract NSIS..."

  rm -rf "$NSIS_EXTRACT"

  mkdir -p "$NSIS_EXTRACT"

  7z x -y -o"$NSIS_EXTRACT" "$INSTALLER" >/dev/null

fi



if [ ! -f "$APP/68助手.exe" ] && [ ! -f "$APP"/*.exe ]; then

  echo "extract app-64.7z..."

  rm -rf "$APP"

  mkdir -p "$APP"

  7z x -y -o"$APP" "$NSIS_EXTRACT/\$PLUGINSDIR/app-64.7z" >/dev/null

fi



rm -rf "$WINEPREFIX"

wineboot --init

sleep 2

mkdir -p "$DEST"

cp -a "$APP"/. "$DEST"/



cat > /home/bot/start68.sh << 'EOF'

#!/bin/bash

export WINEARCH=win64

export WINEPREFIX=/home/bot/.wine68helper

export DISPLAY=:0

export WINEDEBUG=-all

cd "/home/bot/.wine68helper/drive_c/Program Files/68-helper"

exec wine ./68*.exe

EOF

chmod +x /home/bot/start68.sh



cat > /home/bot/Desktop/68-helper.desktop << 'EOF'

[Desktop Entry]

Type=Application

Name=68助手

Exec=/home/bot/start68.sh

Terminal=false

EOF

chmod +x /home/bot/Desktop/68-helper.desktop

gio set /home/bot/Desktop/68-helper.desktop metadata::trusted true 2>/dev/null || true



nohup /home/bot/start68.sh >>/home/bot/68-helper.log 2>&1 &

sleep 12

wmctrl -a otc-pc-chat 2>/dev/null || wmctrl -l

echo OK

"""





def main() -> int:

    os.environ.setdefault("VPS_PASSWORD", "w49-55m-vnc")

    with VpsSSH(load_vps_config(ROOT)) as ssh:

        ssh.run(

            "apt-get update -qq && apt-get install -y -qq p7zip-full wine64 wine32:i386 wmctrl 2>&1 | tail -2",

            300,

        )

        ssh.run(

            "cat > /home/bot/install68.sh << 'EOF'\n" + BOT_SCRIPT + "\nEOF\n"

            "chown bot:bot /home/bot/install68.sh && chmod +x /home/bot/install68.sh",

            20,

        )

        out = ssh.run("runuser -u bot -- /home/bot/install68.sh 2>&1", 180)

        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))

    print("\n已解压部署；桌面点「68助手」看设备码")

    return 0





if __name__ == "__main__":

    raise SystemExit(main())


