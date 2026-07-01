#!/usr/bin/env bash
# 维护窗内二次验通：仅当 19:00 验通失败时才再续期。
set -euo pipefail
R="${BOT_ROOT:-/home/bot/55chat-bot}"
PY="${R}/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
LOG="${R}/logs/tunnel-refresh-retry.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(ts)] === vmos-maintenance-tunnel-retry ===" | tee -a "${LOG}"
cd "${R}"
exec "${PY}" scripts/vmos-refresh-tunnels.py --maintenance-auto --retry-only 2>&1 | tee -a "${LOG}"
