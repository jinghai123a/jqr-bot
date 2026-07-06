#!/usr/bin/env bash
# Ubuntu 24.04：Xfce4 虚拟桌面 DISPLAY=:1 + Wine64 + 55M 电脑版 + WS:5599 监控
set -euo pipefail

WINE="$(command -v wine || command -v wine64 || echo wine)"

export DEBIAN_FRONTEND=noninteractive
ROOT="${BOT_ROOT:-/home/bot/55chat-bot}"
DESKTOP_ROOT="${DESKTOP_ROOT:-/opt/55chat}"
PROTO_ROOT="${PROTO_ROOT:-/home/bot/55chat-protocol}"
WS_PORT="${WS_PORT:-5599}"
VNC_DISPLAY="${VNC_DISPLAY:-:1}"
VNC_GEOM="${VNC_GEOM:-1920x1080}"
BOT_USER="${BOT_USER:-bot}"

log() { echo "[$(date '+%F %T')] $*"; }

ensure_user() {
  id -u "${BOT_USER}" >/dev/null 2>&1 || useradd -m -s /bin/bash "${BOT_USER}"
}

install_desktop_wine() {
  if command -v wine >/dev/null && dpkg -l xfce4 2>/dev/null | grep -q ^ii; then
    log "desktop+wine already installed — skip apt"
    (wine --version || true) | head -1
    return 0
  fi
  log "apt: xfce4 + tigervnc + wine64"
  apt-get update -qq
  apt-get install -y -qq \
    xfce4 xfce4-goodies dbus-x11 \
    tigervnc-standalone-server tigervnc-common \
    wine64 winbind cabextract wget curl unzip git \
    ca-certificates gnupg xvfb firefox
  command -v wine >/dev/null || command -v wine64 >/dev/null
  (wine --version || wine64 --version) 2>/dev/null | head -1
}

setup_vnc() {
  if pgrep -a Xtigervnc >/dev/null 2>&1 && [[ -S /tmp/.X11-unix/X${VNC_DISPLAY#:} ]]; then
    log "VNC already running ${VNC_DISPLAY} — skip"
    return 0
  fi
  local home
  home="$(getent passwd "${BOT_USER}" | cut -d: -f6)"
  local vnc_dir="${home}/.vnc"
  mkdir -p "${vnc_dir}"
  if [[ ! -f "${vnc_dir}/passwd" ]]; then
  echo "w49-55m-vnc" | vncpasswd -f > "${vnc_dir}/passwd"
  chmod 600 "${vnc_dir}/passwd"
  chown -R "${BOT_USER}:${BOT_USER}" "${vnc_dir}"
  fi
  rm -f "${home}/.Xauthority" 2>/dev/null || true
  chown "${BOT_USER}:${BOT_USER}" "${home}" 2>/dev/null || true
  cat > "${vnc_dir}/xstartup" <<'XEOF'
#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_CURRENT_DESKTOP=XFCE
export XDG_SESSION_DESKTOP=xfce
xrdb "$HOME/.Xresources" 2>/dev/null || true
if command -v dbus-launch >/dev/null; then
  exec dbus-launch --exit-with-session xfce4-session
fi
exec startxfce4
XEOF
  chmod +x "${vnc_dir}/xstartup"
  chown -R "${BOT_USER}:${BOT_USER}" "${vnc_dir}"

  # 停旧实例再起 :1
  su - "${BOT_USER}" -c "vncserver -kill ${VNC_DISPLAY} 2>/dev/null || true"
  sleep 1
  su - "${BOT_USER}" -c "vncserver ${VNC_DISPLAY} -geometry ${VNC_GEOM} -depth 24 -localhost no -SecurityTypes VncAuth"
  sleep 3
  if ! pgrep -a Xtigervnc >/dev/null 2>&1; then
    log "retry VNC with xterm fallback"
    su - "${BOT_USER}" -c "vncserver ${VNC_DISPLAY} -geometry ${VNC_GEOM} -depth 24 -localhost no -SecurityTypes VncAuth -xstartup /usr/bin/xterm"
    sleep 2
  fi
  pgrep -a Xtigervnc || pgrep -a Xvnc || { log "FATAL: VNC not running"; exit 1; }
  log "VNC OK ${VNC_DISPLAY}"
}

clone_protocol_repo() {
  log "clone 55chat-bot protocol docs"
  mkdir -p "${PROTO_ROOT}"
  chown -R "${BOT_USER}:${BOT_USER}" "$(dirname "${PROTO_ROOT}")" "${PROTO_ROOT}" 2>/dev/null || true
  if [[ -d "${PROTO_ROOT}/.git" ]]; then
    su - "${BOT_USER}" -c "cd '${PROTO_ROOT}' && git pull --ff-only || true"
  else
    rm -rf "${PROTO_ROOT}"
    su - "${BOT_USER}" -c "git clone --depth 1 https://github.com/yee338024/55chat-bot.git '${PROTO_ROOT}'"
  fi
  chown -R "${BOT_USER}:${BOT_USER}" "${PROTO_ROOT}"
}

install_node_pnpm() {
  if ! command -v node >/dev/null 2>&1; then
    log "install node 20"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs
  fi
  if ! command -v pnpm >/dev/null 2>&1; then
    npm install -g pnpm
  fi
  node -v
  pnpm -v
}

install_ws_client() {
  log "install ws client at ${ROOT}/protocol/55ws-client"
  local client="${ROOT}/protocol/55ws-client"
  mkdir -p "${client}"
  chown -R "${BOT_USER}:${BOT_USER}" "${ROOT}/protocol"
  if [[ -f "${client}/package.json" ]]; then
    su - "${BOT_USER}" -c "cd '${client}' && pnpm install && pnpm run build"
  fi
}

download_55m_windows() {
  mkdir -p "${DESKTOP_ROOT}"
  chown -R "${BOT_USER}:${BOT_USER}" "${DESKTOP_ROOT}"
  local installer="${DESKTOP_ROOT}/55chat-setup.exe"
  if [[ -f "${installer}" ]] && [[ "$(stat -c%s "${installer}" 2>/dev/null || echo 0)" -gt 1000000 ]]; then
    log "installer exists $(stat -c%s "${installer}") bytes"
    return 0
  fi
  log "fetch Windows installer (official mirrors)"
  local ok=0
  local urls=(
    "https://e1.hzxfkj.top/55-im-1.6.6-win-x64-setup.exe"
    "https://55chat.net/download/windows"
    "https://55chat1.com/download/windows"
    "https://563068.com/download/windows"
  )
  for u in "${urls[@]}"; do
    log "try ${u}"
    if curl -fL --max-time 120 -o "${installer}.part" "${u}" 2>/dev/null; then
      if file "${installer}.part" | grep -qiE 'PE32|executable|MS-DOS'; then
        mv "${installer}.part" "${installer}"
        ok=1
        break
      fi
    fi
    rm -f "${installer}.part"
  done
  if [[ "${ok}" -ne 1 ]]; then
    log "WARN: auto-download failed — place 55chat-setup.exe manually at ${installer}"
    return 1
  fi
  chown "${BOT_USER}:${BOT_USER}" "${installer}"
  log "downloaded $(stat -c%s "${installer}") bytes -> ${installer}"
}

setup_wine_prefix() {
  local home
  home="$(getent passwd "${BOT_USER}" | cut -d: -f6)"
  local prefix="${home}/.wine55m"
  su - "${BOT_USER}" -c "export DISPLAY=${VNC_DISPLAY}; export WINEPREFIX='${prefix}'; ${WINE} wineboot --init 2>/dev/null || true"
  log "WINEPREFIX=${prefix}"
}

launch_55m_client() {
  local home installer prefix exe
  home="$(getent passwd "${BOT_USER}" | cut -d: -f6)"
  prefix="${home}/.wine55m"
  local installer="${DESKTOP_ROOT}/55-im-1.7.1-win-x64-setup.exe"
  if [[ ! -f "${installer}" ]]; then
    installer="${DESKTOP_ROOT}/55chat-setup.exe"
  fi
  mkdir -p "${DESKTOP_ROOT}/logs"
  chown -R "${BOT_USER}:${BOT_USER}" "${DESKTOP_ROOT}"

  exe=""
  for cand in \
    "${prefix}/drive_c/users/${BOT_USER}/AppData/Local/Programs/55-im/im.exe" \
    "${prefix}/drive_c/users/${BOT_USER}/AppData/Local/Programs/55/im.exe" \
    "${prefix}/drive_c/Program Files/55-im/im.exe" \
    "${prefix}/drive_c/Program Files (x86)/55-im/im.exe" \
    "${prefix}/drive_c/Program Files/55/55.exe" \
    "${prefix}/drive_c/Program Files (x86)/55/55.exe" \
    "${prefix}/drive_c/Program Files/55Chat/55Chat.exe" \
    "${prefix}/drive_c/Program Files (x86)/55Chat/55Chat.exe" \
    "${DESKTOP_ROOT}/app/im.exe"; do
    if [[ -f "${cand}" ]]; then exe="${cand}"; break; fi
  done
  if [[ -z "${exe}" ]]; then
    exe="$(find "${prefix}/drive_c" -iname 'im.exe' -o -iname '55.exe' -o -iname '55chat.exe' 2>/dev/null | head -1 || true)"
  fi

  su - "${BOT_USER}" -c "export WINEPREFIX='${prefix}'; wineserver -k 2>/dev/null" || true
  sleep 1
  if [[ -n "${exe}" ]]; then
    log "launch ${exe}"
    su - "${BOT_USER}" -c "export DISPLAY=${VNC_DISPLAY}; export WINEPREFIX='${prefix}'; nohup ${WINE} '${exe}' --no-sandbox --disable-gpu >>'${DESKTOP_ROOT}/logs/55m-client.log' 2>&1 &"
  elif [[ -f "${installer}" ]]; then
    log "launch installer UI"
    su - "${BOT_USER}" -c "export DISPLAY=${VNC_DISPLAY}; export WINEPREFIX='${prefix}'; nohup ${WINE} '${installer}' >>'${DESKTOP_ROOT}/logs/55m-client.log' 2>&1 &"
  else
    log "WARN: no exe/installer — manual login required after placing installer"
  fi
  sleep 3
  pgrep -a wine || log "wine not running yet"
}

start_ws_watch() {
  log "start ws watcher on port ${WS_PORT}"
  pkill -f "node watch.js" 2>/dev/null || true
  local client="${ROOT}/protocol/55ws-client"
  export BOT_55WS_LOG_DIR="${DESKTOP_ROOT}/logs"
  if [[ -f "${client}/dist/watch.js" ]]; then
    su - "${BOT_USER}" -c "cd '${client}' && BOT_55WS_LOG_DIR='${DESKTOP_ROOT}/logs' nohup pnpm run watch >>'${DESKTOP_ROOT}/logs/ws-watch.log' 2>&1 &"
  elif [[ -f "${client}/watch.js" ]]; then
    su - "${BOT_USER}" -c "cd '${client}' && BOT_55WS_LOG_DIR='${DESKTOP_ROOT}/logs' nohup node watch.js >>'${DESKTOP_ROOT}/logs/ws-watch.log' 2>&1 &"
  else
    log "WARN: ws client missing"
  fi
}

main() {
  ensure_user
  install_desktop_wine
  setup_vnc
  clone_protocol_repo
  install_node_pnpm
  install_ws_client
  download_55m_windows || true
  setup_wine_prefix
  launch_55m_client
  start_ws_watch
  log "DONE display=${VNC_DISPLAY} vnc_port=$((5900 + ${VNC_DISPLAY#:})) ws=${WS_PORT}"
  ss -lntp | grep -E "590|${WS_PORT}" || true
}

main "$@"
