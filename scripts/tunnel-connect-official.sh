#!/usr/bin/env bash
# VMOS 官方 ADB 隧道：仅原样执行 padApi/adb 返回的 command + adb（见 OpenAPI 文档）。
# 禁止在此脚本内追加 -oHostKeyAlgorithms、ServerAlive 等未出现在 command 里的参数。
tunnel_connect_official() {
  local side_label="${1:-tunnel}"
  : "${LOCAL_PORT:?}"
  : "${SSH_PASS:?}"

  pkill -f "ssh.*${LOCAL_PORT}:" 2>/dev/null || true
  sleep 1

  if [[ -z "${VMOS_SSH_COMMAND:-}" ]]; then
    echo "FATAL [${side_label}]: 缺少 VMOS_SSH_COMMAND（须为 OpenAPI command 字段原文）" >&2
    return 1
  fi

  export SSHPASS="${SSH_PASS}"
  # 官方教程：ssh ... -Nf + key；自动化仅用 sshpass 注入密码，不改 command
  sshpass -e bash -c "${VMOS_SSH_COMMAND}"
  sleep 2

  if [[ -n "${VMOS_ADB_COMMAND:-}" ]]; then
    bash -c "${VMOS_ADB_COMMAND}"
  else
    adb disconnect "127.0.0.1:${LOCAL_PORT}" 2>/dev/null || true
    adb connect "127.0.0.1:${LOCAL_PORT}"
  fi

  adb -s "127.0.0.1:${LOCAL_PORT}" wait-for-device 2>/dev/null \
    || adb -s "localhost:${LOCAL_PORT}" wait-for-device
  echo "OK ${side_label} ADB @ ${LOCAL_PORT} (VMOS official command)"
}
