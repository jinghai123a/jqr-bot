#!/bin/bash
set -euo pipefail
R="${BOT_ROOT:-/home/bot/55chat-bot}"
cd "$R"
# shellcheck disable=SC1091
source "${R}/config/bot-start.env" 2>/dev/null || true
pkill -f 'edge_adb_agent.py' 2>/dev/null || true
sleep 1
export BOT_ROOT="$R"
export EDGE_BRAIN_URL="${EDGE_BRAIN_URL:-http://127.0.0.1:8790}"
export EDGE_LEFT_SERIAL="127.0.0.1:${BOT_CLICKER_ADB_PORT:-52840}"
export EDGE_RIGHT_SERIAL="127.0.0.1:${BOT_LISTENER_ADB_PORT:-58433}"
export EDGE_BRAIN_JWT_SECRET="${EDGE_BRAIN_JWT_SECRET:?EDGE_BRAIN_JWT_SECRET required}"
export EDGE_BRAIN_JWT="${EDGE_BRAIN_JWT:-$("$R/.venv/bin/python3" "$R/scripts/edge_issue_jwt.py" 2>/dev/null | head -1)}"
setsid "$R/.venv/bin/python3" "$R/scripts/edge_adb_agent.py" >>"$R/logs/edge-adb-agent.log" 2>&1 </dev/null &
echo "edge_adb_agent_pid=$!"
