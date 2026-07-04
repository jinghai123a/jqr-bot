#!/usr/bin/env bash
# 生产 cron：维护窗 19:00 全自动续期+验通；19:20 失败重试；20:00 铁律7。
set -euo pipefail
R="${BOT_ROOT:-/home/bot/55chat-bot}"
PY="${R}/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"

(
  echo "CRON_TZ=Asia/Shanghai"
  echo "@reboot sleep 90 && flock -n /tmp/lean-boot.lock bash ${R}/scripts/lean-boot.sh >> ${R}/logs/lean-boot.log 2>&1"
  echo "0 19 * * * flock -n /tmp/vmos-refresh.lock bash ${R}/scripts/vmos-maintenance-tunnel-cycle.sh"
  echo "20 19 * * * flock -n /tmp/vmos-refresh-retry.lock bash ${R}/scripts/vmos-maintenance-tunnel-retry.sh"
  echo "*/15 * * * * flock -n /tmp/tunnel-watch.lock bash ${R}/scripts/watch-adb-tunnels.sh >> ${R}/logs/tunnel-watch.log 2>&1"
  echo "30 */2 * * * flock -n /tmp/vmos-expire.lock cd ${R} && ${PY} scripts/vmos-refresh-tunnels.py --expire-if-needed --reconnect >> ${R}/logs/tunnel-refresh.log 2>&1"
  echo "0 20 * * * flock -n /tmp/daily-mem-cycle.lock cd ${R} && ${PY} scripts/daily_memory_cycle.py >> ${R}/logs/daily-mem-cycle.log 2>&1"
  echo "0 */6 * * * flock -n /tmp/captures-cleanup.lock cd ${R} && BOT_CAPTURES_MAX_FILES=30 ${PY} scripts/vps_captures_cleanup.py >> ${R}/logs/captures-cleanup.log 2>&1"
  echo "30 3 * * 0 flock -n /tmp/purge-apps.lock cd ${R} && ${PY} scripts/purge_unused_apps.py --no-restart >> ${R}/logs/purge-apps.log 2>&1"
  echo "* * * * * flock -n /tmp/kill-legacy.lock bash ${R}/scripts/kill-legacy-if-dual.sh"
) > /tmp/bot-production.cron
crontab /tmp/bot-production.cron
rm -f /tmp/bot-production.cron
echo "[vps_minimal_cron] installed (19:00 tunnel, */15 watch, */2 expire-if-needed, 20:00 mem):"
crontab -l
