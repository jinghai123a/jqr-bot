#!/usr/bin/env bash
# listener right — VMOS 官方 command/adb 原样执行
set -euo pipefail
ROOT="/home/bot/55chat-bot"
# shellcheck disable=SC1091
source "${ROOT}/config/tunnel-right.env"
# shellcheck disable=SC1091
source "${ROOT}/scripts/tunnel-connect-official.sh"
tunnel_connect_official "右机"
