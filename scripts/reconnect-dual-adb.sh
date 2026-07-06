#!/usr/bin/env bash
# 双机隧道：只修复离线的一侧，绝不拆掉正在工作的另一侧。
set -uo pipefail
ROOT="/home/bot/55chat-bot"
cd "$ROOT"
# shellcheck disable=SC1091
source "${ROOT}/config/bot-start.env" 2>/dev/null || true
RPORT="${BOT_LISTENER_ADB_PORT:-60478}"
LPORT="${BOT_CLICKER_ADB_PORT:-56121}"
RADB="${BOT_LISTENER_ADB_SERVER_PORT:-5038}"
LADB="${BOT_CLICKER_ADB_SERVER_PORT:-5039}"
LOG="${ROOT}/logs/tunnel-watch.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

probe_adb() {
  local p="$1"
  local adb_p="$2"
  adb -P "${adb_p}" -s "127.0.0.1:${p}" shell echo OK >/dev/null 2>&1 \
    || adb -P "${adb_p}" -s "localhost:${p}" shell echo OK >/dev/null 2>&1
}

cleanup_stale_adb() {
  while read -r serial _; do
    [[ -n "${serial}" ]] || continue
    adb disconnect "${serial}" 2>/dev/null || true
  done < <(adb devices 2>/dev/null | awk '/offline/{print $1}')
}

heal_side() {
  local name="$1" port="$2" script="$3" adb_p="$4"
  if probe_adb "${port}" "${adb_p}"; then
    echo "[$(ts)] OK ${name} :${port} (skip rebuild)" | tee -a "${LOG}"
    return 0
  fi
  echo "[$(ts)] HEAL ${name} :${port} via ${script}" | tee -a "${LOG}"
  if bash "${ROOT}/scripts/${script}.sh" >>"${LOG}" 2>&1 && probe_adb "${port}" "${adb_p}"; then
    echo "[$(ts)] OK ${name} after ${script}" | tee -a "${LOG}"
    return 0
  fi
  return 1
}

echo "[$(ts)] === reconnect-dual-adb (per-side) ===" | tee -a "${LOG}"
cleanup_stale_adb

RF=0 LF=0
heal_side right "${RPORT}" tunnel-right "${RADB}" || RF=1
heal_side left "${LPORT}" tunnel-left "${LADB}" || LF=1

    if [[ "${RF}" -eq 1 || "${LF}" -eq 1 ]]; then
  if [[ -f "${ROOT}/config/vmos-api.env" && -f "${ROOT}/scripts/vmos-refresh-tunnels.py" ]]; then
    echo "[$(ts)] try VMOS credential refresh (failed sides only)" | tee -a "${LOG}"
    if [[ "${RF}" -eq 1 ]]; then
      python3 "${ROOT}/scripts/vmos-refresh-tunnels.py" --reconnect --side right >>"${LOG}" 2>&1 || true
    fi
    if [[ "${LF}" -eq 1 ]]; then
      python3 "${ROOT}/scripts/vmos-refresh-tunnels.py" --reconnect --side left >>"${LOG}" 2>&1 || true
    fi
    probe_adb "${RPORT}" "${RADB}" && RF=0 || RF=1
    probe_adb "${LPORT}" "${LADB}" && LF=0 || LF=1
  fi
fi

echo "[$(ts)] === adb devices ===" | tee -a "${LOG}"
adb -P "${RADB}" devices -l | tee -a "${LOG}"
adb -P "${LADB}" devices -l | tee -a "${LOG}"

if [[ "${RF}" -eq 0 && "${LF}" -eq 0 ]]; then
  exit 0
fi
echo "[$(ts)] ALERT still down right=${RF} left=${LF}" | tee -a "${LOG}"
exit 1
