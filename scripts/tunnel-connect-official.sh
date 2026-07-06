#!/usr/bin/env bash
# VMOS 官方 ADB 隧道：执行 padApi/adb 返回的 command + adb。
# 仅当 tunnel-*.env 显式设置非空 TUNNEL_SSH_BIND_IP 时才注入 -b（禁止默认回落到左机 IP）。
tunnel_connect_official() {
  local side_label="${1:-tunnel}"
  : "${LOCAL_PORT:?}"
  : "${SSH_PASS:?}"

  local adb_server="${TUNNEL_ADB_SERVER_PORT:-}"
  if [[ -z "${adb_server}" ]]; then
    if [[ "${side_label}" == *左* ]] || [[ "${side_label}" == *left* ]] || [[ "${side_label}" == *CLICKER* ]]; then
      adb_server="${BOT_CLICKER_ADB_SERVER_PORT:-5039}"
    else
      adb_server="${BOT_LISTENER_ADB_SERVER_PORT:-5038}"
    fi
  fi

  probe_adb() {
    adb -P "${adb_server}" -s "127.0.0.1:${LOCAL_PORT}" shell echo OK >/dev/null 2>&1 \
      || adb -P "${adb_server}" -s "localhost:${LOCAL_PORT}" shell echo OK >/dev/null 2>&1
  }

  if probe_adb; then
    echo "[${side_label}] ADB already OK @ ${LOCAL_PORT} (adb -P ${adb_server}, skip rebuild)"
    return 0
  fi

  pkill -f "ssh.*${LOCAL_PORT}:" 2>/dev/null || true
  sleep 1

  if [[ -z "${VMOS_SSH_COMMAND:-}" ]]; then
    echo "FATAL [${side_label}]: 缺少 VMOS_SSH_COMMAND（须为 OpenAPI command 字段原文）" >&2
    return 1
  fi

  local bind_ip="${TUNNEL_SSH_BIND_IP:-}"
  local ssh_cmd="${VMOS_SSH_COMMAND}"
  if [[ -n "${bind_ip}" && "${ssh_cmd}" == ssh\ * && "${ssh_cmd}" != *" -b "* ]]; then
    ssh_cmd="ssh -b ${bind_ip} ${ssh_cmd#ssh }"
  fi

  local pass_file
  pass_file="$(mktemp)"
  chmod 600 "${pass_file}"
  printf '%s' "${SSH_PASS}" >"${pass_file}"
  echo "[${side_label}] ssh bind=${bind_ip:-none} port=${LOCAL_PORT}"
  sshpass -f "${pass_file}" bash -c "${ssh_cmd}" || {
    rm -f "${pass_file}"
    return 1
  }
  rm -f "${pass_file}"
  sleep 2

  if [[ -n "${VMOS_ADB_COMMAND:-}" ]]; then
    local adb_cmd="${VMOS_ADB_COMMAND}"
    if [[ "${adb_cmd}" == adb\ * && "${adb_cmd}" != *" -P "* ]]; then
      adb_cmd="adb -P ${adb_server} ${adb_cmd#adb }"
    fi
    bash -c "${adb_cmd}"
  else
    adb -P "${adb_server}" disconnect "127.0.0.1:${LOCAL_PORT}" 2>/dev/null || true
    adb -P "${adb_server}" connect "127.0.0.1:${LOCAL_PORT}"
  fi

  adb -P "${adb_server}" -s "127.0.0.1:${LOCAL_PORT}" wait-for-device 2>/dev/null \
    || adb -P "${adb_server}" -s "localhost:${LOCAL_PORT}" wait-for-device
  echo "OK ${side_label} ADB @ ${LOCAL_PORT} (VMOS official command)"
}
