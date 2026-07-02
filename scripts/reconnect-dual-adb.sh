#!/usr/bin/env bash
# 双机隧道：只修复离线的一侧，绝不拆掉正在工作的另一侧。
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
ts() { date '+%Y-%m-%d %H:%M:%S'; }

probe_adb() {
  local adb_p="$1" dev_p="$2"
  adb -P "${adb_p}" -s "127.0.0.1:${dev_p}" shell echo OK >/dev/null 2>&1 \
    || adb -P "${adb_p}" -s "localhost:${dev_p}" shell echo OK >/dev/null 2>&1
}

connect_side() {
  local adb_p="$1" dev_p="$2"
  adb -P "${adb_p}" start-server >/dev/null 2>&1 || true
  adb -P "${adb_p}" connect "127.0.0.1:${dev_p}" >/dev/null 2>&1 || true
  adb -P "${adb_p}" connect "localhost:${dev_p}" >/dev/null 2>&1 || true
}

cleanup_stale_adb() {
  for adb_p in "${RADB}" "${LADB}"; do
    while read -r serial _; do
      [[ -n "${serial}" ]] || continue
      adb -P "${adb_p}" disconnect "${serial}" 2>/dev/null || true
    done < <(adb -P "${adb_p}" devices 2>/dev/null | awk '/offline/{print $1}')
    while read -r serial _; do
      [[ -n "${serial}" ]] || continue
      case "${serial}" in
        emulator-*|unknown) adb -P "${adb_p}" disconnect "${serial}" 2>/dev/null || true ;;
      esac
    done < <(adb -P "${adb_p}" devices 2>/dev/null | awk 'NR>1 && $2!="device"{print $1}')
  done
}

dedupe_side() {
  local adb_p="$1" dev_p="$2"
  if probe_adb "${adb_p}" "${dev_p}"; then
    adb -P "${adb_p}" disconnect "localhost:${dev_p}" 2>/dev/null || true
  elif adb -P "${adb_p}" -s "localhost:${dev_p}" shell echo OK >/dev/null 2>&1; then
    adb -P "${adb_p}" disconnect "127.0.0.1:${dev_p}" 2>/dev/null || true
  fi
  adb -P "${adb_p}" disconnect "emulator-5554" 2>/dev/null || true
}

heal_side() {
  local name="$1" adb_p="$2" dev_p="$3" script="$4"
  connect_side "${adb_p}" "${dev_p}"
  if probe_adb "${adb_p}" "${dev_p}"; then
    echo "[$(ts)] OK ${name} adb:${adb_p} dev:${dev_p} (skip rebuild)" | tee -a "${LOG}"
    return 0
  fi
  echo "[$(ts)] HEAL ${name} adb:${adb_p} dev:${dev_p} via ${script}" | tee -a "${LOG}"
  if bash "${ROOT}/scripts/${script}.sh" >>"${LOG}" 2>&1; then
    connect_side "${adb_p}" "${dev_p}"
    if probe_adb "${adb_p}" "${dev_p}"; then
      echo "[$(ts)] OK ${name} after ${script}" | tee -a "${LOG}"
      return 0
    fi
  fi
  return 1
}

echo "[$(ts)] === reconnect-dual-adb (per-side) ===" | tee -a "${LOG}"
cleanup_stale_adb

RF=0 LF=0
heal_side right "${RADB}" "${RPORT}" tunnel-right || RF=1
heal_side left "${LADB}" "${LPORT}" tunnel-left || LF=1

dedupe_side "${RADB}" "${RPORT}"
dedupe_side "${LADB}" "${LPORT}"

    if [[ "${RF}" -eq 1 || "${LF}" -eq 1 ]]; then
  if [[ -f "${ROOT}/config/vmos-api.env" && -f "${ROOT}/scripts/vmos-refresh-tunnels.py" ]]; then
    echo "[$(ts)] try VMOS credential refresh (failed sides only)" | tee -a "${LOG}"
    if [[ "${RF}" -eq 1 ]]; then
      python3 "${ROOT}/scripts/vmos-refresh-tunnels.py" --reconnect --side right >>"${LOG}" 2>&1 || true
    fi
    if [[ "${LF}" -eq 1 ]]; then
      python3 "${ROOT}/scripts/vmos-refresh-tunnels.py" --reconnect --side left >>"${LOG}" 2>&1 || true
    fi
    connect_side "${RADB}" "${RPORT}"
    connect_side "${LADB}" "${LPORT}"
    probe_adb "${RADB}" "${RPORT}" && RF=0 || RF=1
    probe_adb "${LADB}" "${LPORT}" && LF=0 || LF=1
  fi
fi

echo "[$(ts)] === adb devices (5038 listener / 5039 clicker) ===" | tee -a "${LOG}"
adb -P "${RADB}" devices -l | tee -a "${LOG}"
adb -P "${LADB}" devices -l | tee -a "${LOG}"

if [[ "${RF}" -eq 0 && "${LF}" -eq 0 ]]; then
  exit 0
fi
echo "[$(ts)] ALERT still down right=${RF} left=${LF}" | tee -a "${LOG}"
exit 1
