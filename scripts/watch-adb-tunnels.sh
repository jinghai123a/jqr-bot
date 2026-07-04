#!/usr/bin/env bash
# 每 15 分钟 cron：检测双机 ADB，断开则自动重建隧道（密码过期需人工更新 tunnel-*.env）
set -euo pipefail
ROOT="/home/bot/55chat-bot"
LOG="${ROOT}/logs/tunnel-watch.log"
mkdir -p "${ROOT}/logs"
# shellcheck disable=SC1091
source "${ROOT}/config/bot-start.env" 2>/dev/null || true
RPORT="${BOT_LISTENER_ADB_PORT:-60478}"
LPORT="${BOT_CLICKER_ADB_PORT:-56121}"
RADB="${BOT_LISTENER_ADB_SERVER_PORT:-5038}"
LADB="${BOT_CLICKER_ADB_SERVER_PORT:-5039}"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

probe() {
  local p="$1"
  local adb_p="$2"
  adb -P "${adb_p}" -s "127.0.0.1:${p}" shell echo OK >/dev/null 2>&1 \
    || adb -P "${adb_p}" -s "localhost:${p}" shell echo OK >/dev/null 2>&1
}

ok_r=0 ok_l=0
probe "$RPORT" "$RADB" && ok_r=1 || true
probe "$LPORT" "$LADB" && ok_l=1 || true

if [[ "$ok_r" -eq 1 && "$ok_l" -eq 1 ]]; then
  echo "[$(ts)] OK right=${RPORT} left=${LPORT}" >>"$LOG"
  exit 0
fi

echo "[$(ts)] FAIL right=${ok_r} left=${ok_l} — reconnect" >>"$LOG"
cd "$ROOT"
bash scripts/reconnect-dual-adb.sh >>"$LOG" 2>&1 || true
sleep 3
probe "$RPORT" "$RADB" && ok_r=1 || ok_r=0
probe "$LPORT" "$LADB" && ok_l=1 || ok_l=0
echo "[$(ts)] after reconnect right=${ok_r} left=${ok_l}" >>"$LOG"

if [[ "$ok_r" -eq 0 || "$ok_l" -eq 0 ]]; then
  if [[ -f "${ROOT}/config/vmos-api.env" && -f "${ROOT}/scripts/vmos-refresh-tunnels.py" ]]; then
    echo "[$(ts)] try VMOS API refresh" >>"$LOG"
    python3 "${ROOT}/scripts/vmos-refresh-tunnels.py" --reconnect >>"$LOG" 2>&1 || true
    sleep 3
    probe "$RPORT" "$RADB" && ok_r=1 || ok_r=0
    probe "$LPORT" "$LADB" && ok_l=1 || ok_l=0
    echo "[$(ts)] after vmos refresh right=${ok_r} left=${ok_l}" >>"$LOG"
  fi
fi

if [[ "$ok_r" -eq 0 || "$ok_l" -eq 0 ]]; then
  echo "[$(ts)] ALERT: 隧道仍失败，检查 VMOS API 或手动更新 config/tunnel-*.env" >>"$LOG"
  exit 1
fi
