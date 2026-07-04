#!/bin/bash
# 全自动：ADB reverse + AutoJs6 下载安装 + 脚本推送 + 启动（无需人工）
set -euo pipefail
R="${BOT_ROOT:-/home/bot/55chat-bot}"
cd "$R"
# shellcheck disable=SC1091
source "${R}/config/bot-start.env" 2>/dev/null || true
mkdir -p artifacts logs

APK="$R/artifacts/autojs6-arm64.apk"
APK_URL="${AUTOJS6_APK_URL:-https://github.com/SuperMonster003/AutoJs6/releases/download/v6.7.0/autojs6-v6.7.0-arm64-v8a-62db1ff8.apk}"
PKG="org.autojs.autojs6"

if [ ! -s "$APK" ]; then
  echo "[auto] download AutoJs6..."
  wget -q -O "$APK" "$APK_URL" || curl -fsSL -o "$APK" "$APK_URL"
fi
ls -lh "$APK"

bash "${R}/scripts/edge_adb_connect.sh" 2>&1 | tail -3

ADB_L=(adb -P "${BOT_CLICKER_ADB_SERVER_PORT:-5039}" -s "127.0.0.1:${BOT_CLICKER_ADB_PORT:-52840}")
ADB_R=(adb -P "${BOT_LISTENER_ADB_SERVER_PORT:-5038}" -s "127.0.0.1:${BOT_LISTENER_ADB_PORT:-58433}")

"${ADB_L[@]}" reverse tcp:8790 tcp:8790 2>/dev/null || true
"${ADB_R[@]}" reverse tcp:8790 tcp:8790 2>/dev/null || true

echo "[auto] install AutoJs6 left..."
"${ADB_L[@]}" install -r -g "$APK" 2>&1 | tail -2
echo "[auto] install AutoJs6 right..."
"${ADB_R[@]}" install -r -g "$APK" 2>&1 | tail -2

"${ADB_L[@]}" shell mkdir -p /sdcard/Scripts/w49-settle-left
"${ADB_R[@]}" shell mkdir -p /sdcard/Scripts/w49-listener-right

"${ADB_L[@]}" push "$R/edge_android/settle-left/settle_left.js" /sdcard/Scripts/w49-settle-left/settle_left.js
"${ADB_L[@]}" push "$R/edge_android/settle-left/edge_config.json" /sdcard/Scripts/w49-settle-left/edge_config.json
"${ADB_R[@]}" push "$R/edge_android/listener-right/listener_right.js" /sdcard/Scripts/w49-listener-right/listener_right.js
"${ADB_R[@]}" push "$R/edge_android/listener-right/edge_config.json" /sdcard/Scripts/w49-listener-right/edge_config.json

for side in L R; do
  if [ "$side" = L ]; then ADB=( "${ADB_L[@]}" ); else ADB=( "${ADB_R[@]}" ); fi
  SVC=$("${ADB[@]}" shell cmd accessibility list-services 2>/dev/null | grep -i autojs | head -1 | tr -d '\r' || true)
  if [ -n "$SVC" ]; then
    "${ADB[@]}" shell settings put secure enabled_accessibility_services "$SVC" 2>/dev/null || true
    "${ADB[@]}" shell settings put secure accessibility_enabled 1 2>/dev/null || true
    echo "[auto] a11y ${side}=${SVC}"
  fi
done

RUN_ACT="${PKG}/org.autojs.autojs.external.open.RunIntentActivity"
AUTOJS6="${BOT_EDGE_AUTOJS6:-0}"
EDGE_AGENT="${BOT_EDGE_ADB_AGENT:-0}"

if [[ "${AUTOJS6}" == "1" ]]; then
  echo "[auto] BOT_EDGE_AUTOJS6=1 → 仅启动左机 settle_left.js"
  "${ADB_L[@]}" shell am start -n "$RUN_ACT" \
    -d "file:///sdcard/Scripts/w49-settle-left/settle_left.js" -t "text/javascript" 2>/dev/null || true
else
  echo "[auto] BOT_EDGE_AUTOJS6=0 → 跳过 AutoJs6（生产走 bot_dual_supervisor）"
  "${ADB_L[@]}" shell am force-stop "${PKG}" 2>/dev/null || true
  "${ADB_R[@]}" shell am force-stop "${PKG}" 2>/dev/null || true
fi

if [[ "${EDGE_AGENT}" == "1" ]]; then
  bash "${R}/scripts/edge_adb_agent_start.sh" 2>/dev/null || true
else
  pkill -f 'edge_adb_agent.py' 2>/dev/null || true
  echo "[auto] BOT_EDGE_ADB_AGENT=0 → 不启 edge_adb_agent"
fi

echo "[auto] AutoJs6 bootstrap done"
