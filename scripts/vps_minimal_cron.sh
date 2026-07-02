#!/usr/bin/env bash
# 生产 cron：维护窗 19:00 全自动续期+验通；19:20 失败重试；19:35 铁律7（维护窗结束后，OpenAPI 不占隧道）。
set -euo pipefail
R="${BOT_ROOT:-/home/bot/55chat-bot}"
PY="${R}/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
# shellcheck disable=SC1091
source "${R}/config/bot-start.env" 2>/dev/null || true
MEM_CRON="${BOT_DAILY_MEM_CYCLE_CRON:-35 19}"

(
  echo "CRON_TZ=Asia/Shanghai"
  echo "@reboot sleep 90 && flock -n /tmp/lean-boot.lock bash ${R}/scripts/lean-boot.sh >> ${R}/logs/lean-boot.log 2>&1"
  echo "0 19 * * * flock -n /tmp/vmos-refresh.lock bash ${R}/scripts/vmos-maintenance-tunnel-cycle.sh"
  echo "20 19 * * * flock -n /tmp/vmos-refresh-retry.lock bash ${R}/scripts/vmos-maintenance-tunnel-retry.sh"
  echo "${MEM_CRON} * * * flock -n /tmp/daily-mem-cycle.lock cd ${R} && ${PY} scripts/daily_memory_cycle.py >> ${R}/logs/daily-mem-cycle.log 2>&1"
  echo "* * * * * flock -n /tmp/kill-legacy.lock bash ${R}/scripts/kill-legacy-if-dual.sh"
) > /tmp/bot-production.cron
crontab /tmp/bot-production.cron
rm -f /tmp/bot-production.cron
echo "[vps_minimal_cron] installed (19:00 tunnel, 19:20 retry, ${MEM_CRON} mem-cycle):"
crontab -l
