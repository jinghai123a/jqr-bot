#!/usr/bin/env bash
# 任务收尾：双端 ADB 隧道必须畅通，禁止 localhost/127.0.0.1 重复连接拥堵。
set -uo pipefail
ROOT="/home/bot/55chat-bot"
cd "$ROOT"
# shellcheck disable=SC1091
source "${ROOT}/config/bot-start.env" 2>/dev/null || true
RPORT="${BOT_LISTENER_ADB_PORT:-58433}"
LPORT="${BOT_CLICKER_ADB_PORT:-52840}"
RADB="${BOT_LISTENER_ADB_SERVER_PORT:-5038}"
LADB="${BOT_CLICKER_ADB_SERVER_PORT:-5039}"
LOG="${ROOT}/logs/tunnel-watch.log"
PROBE_TIMEOUT="${BOT_TUNNEL_PROBE_TIMEOUT:-10}"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

probe_side() {
  local adb_p="$1" dev_p="$2"
  timeout "${PROBE_TIMEOUT}" adb -P "${adb_p}" -s "127.0.0.1:${dev_p}" shell echo OK >/dev/null 2>&1 \
    || timeout "${PROBE_TIMEOUT}" adb -P "${adb_p}" -s "localhost:${dev_p}" shell echo OK >/dev/null 2>&1
}

echo "[$(ts)] === post-task tunnel verify ===" | tee -a "${LOG}"

if ! bash "${ROOT}/scripts/reconnect-dual-adb.sh" >>"${LOG}" 2>&1; then
  echo "[$(ts)] reconnect-dual-adb failed" | tee -a "${LOG}"
  exit 1
fi

RF=0 LF=0
probe_side "${RADB}" "${RPORT}" || RF=1
probe_side "${LADB}" "${LPORT}" || LF=1

echo "[$(ts)] probe right=${RF} left=${LF} (0=OK)" | tee -a "${LOG}"
adb -P "${RADB}" devices -l | tee -a "${LOG}"
adb -P "${LADB}" devices -l | tee -a "${LOG}"

if [[ "${RF}" -eq 0 && "${LF}" -eq 0 ]]; then
  echo "[$(ts)] TUNNEL_OK dual adb responsive" | tee -a "${LOG}"
  exit 0
fi
echo "[$(ts)] TUNNEL_FAIL right=${RF} left=${LF}" | tee -a "${LOG}"
exit 1
