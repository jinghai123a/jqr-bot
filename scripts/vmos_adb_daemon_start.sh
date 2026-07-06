#!/usr/bin/env bash
# VMOS OpenAPI 动态 ADB 续期守护 — 启停 + 停止死循环重试脚本
set -euo pipefail
ROOT="${BOT_ROOT:-/home/bot/55chat-bot}"
PY="${ROOT}/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
PIDFILE="${ROOT}/data/vmos_adb_daemon.pid"
LOG="${ROOT}/logs/vmos-adb-daemon.log"
DAEMON="${ROOT}/scripts/vmos_adb_daemon.py"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

stop_dead_loops() {
  pkill -9 -f vps_force_left_tunnel_loop.py 2>/dev/null || true
  pkill -9 -f vps_force_right_tunnel_loop.py 2>/dev/null || true
  pkill -9 -f vmos_direct_adb_refresh.py 2>/dev/null || true
  pkill -9 -f vps_revive_panel_dual_now.py 2>/dev/null || true
  pkill -9 -f vmos_api_local_refresh.py 2>/dev/null || true
  rm -f "${ROOT}/data/vmos-refresh.lock" "${ROOT}/logs/.vmos-refresh.lock" 2>/dev/null || true
  echo "[$(ts)] stopped legacy tunnel retry loops"
}

stop_daemon() {
  if [[ -f "$PIDFILE" ]]; then
    old_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
      kill "${old_pid}" 2>/dev/null || true
      sleep 2
      kill -9 "${old_pid}" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
  fi
  pkill -f "vmos_adb_daemon.py --daemon" 2>/dev/null || true
}

start_daemon() {
  mkdir -p "${ROOT}/data" "${ROOT}/logs"
  stop_dead_loops
  stop_daemon
  if pgrep -f "vmos_adb_daemon.py --daemon" >/dev/null 2>&1; then
    echo "[$(ts)] daemon already running"
    exit 0
  fi
  cd "$ROOT"
  nohup "$PY" "$DAEMON" --daemon >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  sleep 2
  echo "[$(ts)] vmos_adb_daemon started pid=$(cat "$PIDFILE") log=$LOG"
}

status_daemon() {
  if pgrep -af "vmos_adb_daemon.py" | grep -v pgrep; then
    echo "daemon: running"
  else
    echo "daemon: stopped"
  fi
  "$PY" "$DAEMON" --status 2>/dev/null | tail -20 || true
}

case "${1:-start}" in
  start) start_daemon ;;
  stop) stop_daemon; stop_dead_loops ;;
  restart) stop_daemon; start_daemon ;;
  status) status_daemon ;;
  once) cd "$ROOT" && exec "$PY" "$DAEMON" --once ;;
  urgent) cd "$ROOT" && exec "$PY" "$DAEMON" --urgent ;;
  *) echo "usage: $0 {start|stop|restart|status|once|urgent}"; exit 1 ;;
esac
