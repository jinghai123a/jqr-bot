#!/bin/bash
# 双机 ADB 挂到隔离 server（5038/5039），供 edge bootstrap / edge_adb_agent 使用
set -euo pipefail
R="${BOT_ROOT:-/home/bot/55chat-bot}"
# shellcheck disable=SC1091
source "${R}/config/bot-start.env" 2>/dev/null || true
RPORT="${BOT_LISTENER_ADB_PORT:-58433}"
LPORT="${BOT_CLICKER_ADB_PORT:-52840}"
RSERVER="${BOT_LISTENER_ADB_SERVER_PORT:-5038}"
LSERVER="${BOT_CLICKER_ADB_SERVER_PORT:-5039}"

connect_one() {
  local srv="$1" port="$2" label="$3"
  local serial="127.0.0.1:${port}"
  adb -P "${srv}" disconnect "${serial}" 2>/dev/null || true
  adb -P "${srv}" disconnect "localhost:${port}" 2>/dev/null || true
  adb -P "${srv}" connect "${serial}" 2>/dev/null || true
  if ! timeout 45 adb -P "${srv}" -s "${serial}" wait-for-device 2>/dev/null; then
    serial="localhost:${port}"
    timeout 45 adb -P "${srv}" -s "${serial}" wait-for-device 2>/dev/null \
      || { echo "WARN ${label} adb not ready port=${port}"; return 1; }
  fi
  adb -P "${srv}" -s "${serial}" shell echo "OK_${label}" 2>/dev/null \
    || adb -P "${srv}" -s "localhost:${port}" shell echo "OK_${label}"
}

connect_one "${RSERVER}" "${RPORT}" RIGHT || true
connect_one "${LSERVER}" "${LPORT}" LEFT || true
echo "edge_adb_connect OK R=${RSERVER}:127.0.0.1:${RPORT} L=${LSERVER}:127.0.0.1:${LPORT}"
