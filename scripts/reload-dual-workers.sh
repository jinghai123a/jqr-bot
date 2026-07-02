#!/usr/bin/env bash
# 滚动热更新：仅重启 worker 子进程；失败则仅重启 supervisor（不碰隧道/ADB）。
set -euo pipefail
R="${BOT_ROOT:-/home/bot/55chat-bot}"
cd "$R"
PY="${R}/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

if ! pgrep -f "bot_dual_supervisor.py" >/dev/null 2>&1; then
  echo "no supervisor — fallback full restart"
  bash "$R/scripts/restart-55chat-bot.sh"
  exit $?
fi

"$PY" -m py_compile "$R/bot_55chat_daemon.py" "$R/bot_dual_supervisor.py" 2>/dev/null || true
pkill -9 -f 'python3 -u bot_55chat_daemon.py' 2>/dev/null || true
find "$R" -type d -name __pycache__ 2>/dev/null | head -30 | xargs rm -rf 2>/dev/null || true

pkill -TERM -f 'spawn_main(tracker_fd' 2>/dev/null || true
sleep 2
pkill -9 -f 'spawn_main(tracker_fd' 2>/dev/null || true

n=0
for _ in $(seq 1 45); do
  n=$(pgrep -fc 'spawn_main(tracker_fd' 2>/dev/null | tr -d '[:space:]' || echo 0)
  n="${n:-0}"
  if [[ "$n" -ge 2 ]]; then
    echo "reload_ok spawn_children=$n supervisor=$(pgrep -f bot_dual_supervisor.py | head -1)"
    exit 0
  fi
  sleep 2
done

echo "reload slow — restart supervisor only (keep tunnels)" | tee -a "${R}/logs/dual-supervisor.log"
pkill -TERM -f 'bot_dual_supervisor.py' 2>/dev/null || true
sleep 2
pkill -9 -f 'spawn_main(tracker_fd' 2>/dev/null || true
pkill -9 -f 'bot_dual_supervisor.py' 2>/dev/null || true
rm -f "$R/data/bot.lock.listener" "$R/data/bot.lock.clicker"
nohup "$PY" -u "$R/bot_dual_supervisor.py" >> "$R/logs/dual-supervisor.log" 2>&1 &
for _ in $(seq 1 30); do
  n=$(pgrep -fc 'spawn_main(tracker_fd' 2>/dev/null | tr -d '[:space:]' || echo 0)
  n="${n:-0}"
  if [[ "$n" -ge 2 ]]; then
    echo "supervisor_restart_ok spawn_children=$n"
    exit 0
  fi
  sleep 2
done
echo "FATAL: supervisor restart timeout spawn_children=$n" >&2
tail -20 "$R/logs/dual-supervisor.log" >&2 || true
exit 1
