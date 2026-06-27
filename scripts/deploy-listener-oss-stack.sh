#!/usr/bin/env bash
# 右机 LISTENER 开源栈（bot 暂停时部署）
# 组件：uiautomator2 agent + adb-clip + ADB Keyboard
# 注意：业务 worker 线程跑在 VPS，不在云机 Android 内
set -euo pipefail
ROOT="/home/bot/55chat-bot"
# shellcheck disable=SC1091
source "${ROOT}/config/bot-start.env" 2>/dev/null || true
RPORT="${BOT_LISTENER_ADB_PORT:-54936}"
WUWU_PKG="wuwu.d260619.t0600.d9vlmf481w"
ADBKB_PKG="com.android.adbkeyboard"
ADBKB_APK_URL="https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk"
CLIP_BASE="https://github.com/polygraphene/adb-clip/releases/download/v0.0.3"
LOG="${ROOT}/logs/oss-stack-right.log"
mkdir -p "${ROOT}/logs"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

pick_serial() {
  local port="$1"
  if adb -s "127.0.0.1:${port}" shell echo OK >/dev/null 2>&1; then
    echo "127.0.0.1:${port}"
  elif adb -s "localhost:${port}" shell echo OK >/dev/null 2>&1; then
    echo "localhost:${port}"
  else
    return 1
  fi
}

log "=== 右机 OSS 栈部署开始（不启动 bot）==="
bash "${ROOT}/scripts/tunnel-right.sh" >>"$LOG" 2>&1 || true
SERIAL="$(pick_serial "$RPORT")" || { log "FAIL: 右机 ADB 离线"; exit 1; }
log "serial=${SERIAL}"

# 1) adb-clip — 外部文本写入系统剪贴板
log "--- adb-clip ---"
adb -s "$SERIAL" shell \
  "curl -fsSL -o /data/local/tmp/clip.jar ${CLIP_BASE}/clip.jar && curl -fsSL -o /data/local/tmp/clip ${CLIP_BASE}/clip && chmod 755 /data/local/tmp/clip" \
  >>"$LOG" 2>&1 || log "adb-clip warn"
test_text="oss_clip_$(date +%s)"
if adb -s "$SERIAL" shell /data/local/tmp/clip set "$test_text" >>"$LOG" 2>&1; then
  got="$(adb -s "$SERIAL" shell /data/local/tmp/clip get 2>/dev/null | tr -d '\r\n' || true)"
  if [[ "$got" == *"$test_text"* ]]; then
    log "adb-clip OK"
  else
    adb -s "$SERIAL" shell cmd clipboard set-text "$test_text" >>"$LOG" 2>&1 || true
    log "adb-clip fallback cmd.clipboard"
  fi
else
  adb -s "$SERIAL" shell cmd clipboard set-text "$test_text" >>"$LOG" 2>&1 || true
  log "adb-clip via cmd only"
fi

# 2) ADB Keyboard — 中文/长文 B64 注入（不依赖剪贴板）
log "--- ADB Keyboard ---"
tmp_kb="/tmp/ADBKeyboard-right.apk"
curl -fsSL -o "$tmp_kb" "$ADBKB_APK_URL" >>"$LOG" 2>&1
adb -s "$SERIAL" install -r "$tmp_kb" >>"$LOG" 2>&1 || true
rm -f "$tmp_kb"
adb -s "$SERIAL" shell ime enable "${ADBKB_PKG}/.AdbIME" >>"$LOG" 2>&1 || true
adb -s "$SERIAL" shell ime set "${ADBKB_PKG}/.AdbIME" >>"$LOG" 2>&1 || true
log "ADB Keyboard enabled"

# 3) uiautomator2 — 推送 atx-agent / u2.jar（读屏+pasteClipboard）
log "--- uiautomator2 agent ---"
if python3 -c "import uiautomator2" 2>/dev/null; then
  python3 - <<PY >>"$LOG" 2>&1 || log "u2 init warn"
import uiautomator2 as u2
d = u2.connect("${SERIAL}")
info = d.info
print("u2 connected", info.get("productName"), info.get("displayWidth"), "x", info.get("displayHeight"))
PY
else
  log "uiautomator2 pip 未装，跳过 agent 初始化"
fi

# 4) 启动 55M 到前台（不导航，仅确保 IM 在）
log "--- 55M foreground ---"
adb -s "$SERIAL" shell monkey -p "$WUWU_PKG" -c android.intent.category.LAUNCHER 1 >>"$LOG" 2>&1 \
  || adb -s "$SERIAL" shell am start -n "${WUWU_PKG}/.MainActivity" >>"$LOG" 2>&1 || true

log "=== 右机 OSS 栈部署完成（bot 仍暂停）==="
adb -s "$SERIAL" shell pm list packages -3 | grep -E 'adbkeyboard|wuwu' | tee -a "$LOG" || true
ls -la /data/local/tmp/clip /data/local/tmp/u2.jar 2>/dev/null | adb -s "$SERIAL" shell 'ls -la /data/local/tmp/clip /data/local/tmp/u2.jar 2>/dev/null' | tee -a "$LOG" || true
