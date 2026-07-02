#!/usr/bin/env bash
# dual_supervisor 在跑时，杀掉 legacy MONO 竞品（与 spawn 抢锁/抢群）
set -euo pipefail
pgrep -f 'bot_dual_supervisor.py' >/dev/null || exit 0
for pid in $(pgrep -f 'python3 -u bot_55chat_daemon.py' 2>/dev/null || true); do
  kill -9 "$pid" 2>/dev/null || true
done
