#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT="${LAB_ROOT:-/opt/55m-lab}"
R="${BOT_ROOT:-${LAB_ROOT}/app}"
cd "$R"
export PATH="${LAB_ROOT}/.venv/bin:$PATH"
export BOT_ROOT="$R"
# shellcheck disable=SC1091
source "${R}/config/bot-start.env" 2>/dev/null || true

export EDGE_BRAIN_HOST="${EDGE_BRAIN_HOST:-0.0.0.0}"
export EDGE_BRAIN_PORT="${EDGE_BRAIN_PORT:-8790}"
export EDGE_BRAIN_JWT_SECRET="${EDGE_BRAIN_JWT_SECRET:-w49-edge-jwt-secret-dev-only}"
export EDGE_BRAIN_JWT="${EDGE_BRAIN_JWT:-}"
export BOT_PANEL_URL="${BOT_PANEL_URL:-http://127.0.0.1:3000}"

mkdir -p "${LAB_ROOT}/logs" "${LAB_ROOT}/data/edge_brain" "${R}/logs"
ln -sfn "${LAB_ROOT}/logs" "${R}/logs/lab" 2>/dev/null || true
ln -sfn "${LAB_ROOT}/data" "${R}/data/lab" 2>/dev/null || true

pkill -f 'edge_mock_panel.py' 2>/dev/null || true
pkill -f 'python.*-m edge_brain' 2>/dev/null || true
pkill -f 'edge_adb_agent.py' 2>/dev/null || true
sleep 1

if ! curl -sf "${BOT_PANEL_URL}/api/bots" >/dev/null 2>&1; then
  setsid "${LAB_ROOT}/.venv/bin/python3" "$R/scripts/edge_mock_panel.py" >>"${LAB_ROOT}/logs/mock-panel.log" 2>&1 </dev/null &
  sleep 1
fi

export EDGE_BRAIN_PORT EDGE_BRAIN_JWT_SECRET EDGE_BRAIN_JWT EDGE_BRAIN_HOST
bash "$R/scripts/edge_brain_start.sh"
sleep 2
curl -sf "http://127.0.0.1:${EDGE_BRAIN_PORT}/health" || { echo "edge_brain FAIL"; exit 1; }

bash "$R/scripts/reconnect-dual-adb.sh" 2>&1 | tail -15 || true
bash "$R/scripts/edge_adb_connect.sh" 2>&1 || true
bash "$R/scripts/edge_auto_bootstrap.sh" 2>&1 | tail -25 || true
bash "$R/scripts/edge_adb_agent_start.sh"

pgrep -af 'edge_brain|edge_adb_agent|edge_mock_panel' | grep -v pgrep || true
echo "GUEST_EDGE_STACK_OK ${LAB_ROOT}"
