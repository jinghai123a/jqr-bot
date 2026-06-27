#!/usr/bin/env bash
# 双机 ADB 探活：任一离线 → refresh 隧道 + reconnect
set -euo pipefail
ROOT="/home/bot/55chat-bot"
# shellcheck disable=SC1091
source "${ROOT}/config/bot-start.env" 2>/dev/null || true
RPORT="${BOT_LISTENER_ADB_PORT:-60478}"
LPORT="${BOT_CLICKER_ADB_PORT:-56121}"
LOG="${ROOT}/logs/tunnel-watch.log"
mkdir -p "${ROOT}/logs"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

probe() {
  local p="$1"
  adb -s "127.0.0.1:${p}" shell echo OK >/dev/null 2>&1 \
    || adb -s "localhost:${p}" shell echo OK >/dev/null 2>&1
}

ok_r=0 ok_l=0
probe "$RPORT" && ok_r=1 || true
probe "$LPORT" && ok_l=1 || true

if [[ "$ok_r" -eq 1 && "$ok_l" -eq 1 ]]; then
  exit 0
fi

echo "[$(ts)] watchdog FAIL right=${ok_r} left=${ok_l}" >>"$LOG"
cd "$ROOT"
bash scripts/watch-adb-tunnels.sh >>"$LOG" 2>&1 || true
