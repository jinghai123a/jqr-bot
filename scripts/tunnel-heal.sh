#!/usr/bin/env bash
# daemon / cron 统一入口：按侧探活 + 按需刷新 VMOS 凭证（7 天有效期）
exec /home/bot/55chat-bot/scripts/reconnect-dual-adb.sh "$@"
