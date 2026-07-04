#!/bin/bash
set -e
R="${BOT_ROOT:-/home/bot/55chat-bot}"
cd "$R"
mkdir -p logs
# shellcheck disable=SC1091
source "${R}/config/bot-start.env" 2>/dev/null || true
pkill -f 'python.*-m edge_brain' 2>/dev/null || true
sleep 1
export EDGE_BRAIN_HOST="${EDGE_BRAIN_HOST:-0.0.0.0}"
export EDGE_BRAIN_PORT="${EDGE_BRAIN_PORT:-8790}"
export EDGE_BRAIN_JWT_SECRET="${EDGE_BRAIN_JWT_SECRET:-w49-edge-aps-jwt-secret}"
export BOT_ROOT="$R"
export BOT_PANEL_URL="${BOT_PANEL_URL:-http://127.0.0.1:3000}"
setsid "$R/.venv/bin/python3" -m edge_brain >>"$R/logs/edge-brain.log" 2>&1 </dev/null &
echo "edge_brain_pid=$!"
