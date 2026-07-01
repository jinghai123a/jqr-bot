#!/usr/bin/env bash
# 维护窗全自动闭环：OpenAPI 续期 → 双端验通 → 失败再续（§0 例外，非手动）。
set -euo pipefail
R="${BOT_ROOT:-/home/bot/55chat-bot}"
PY="${R}/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
LOG="${R}/logs/tunnel-refresh.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(ts)] === vmos-maintenance-tunnel-cycle ===" | tee -a "${LOG}"
cd "${R}"
exec "${PY}" scripts/vmos-refresh-tunnels.py --maintenance-auto 2>&1 | tee -a "${LOG}"
