#!/usr/bin/env bash
# VM 内初始化 /opt/55m-lab 专区 + 全量 pip 模块
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

LAB_ROOT="${LAB_ROOT:-/opt/55m-lab}"
APP_ROOT="${APP_ROOT:-${LAB_ROOT}/app}"
BOT_USER="${BOT_USER:-bot}"
VENV="${LAB_ROOT}/.venv"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "sudo bash guest_bootstrap.sh"
  exit 1
fi

apt-get update -qq
apt-get install -y -qq \
  python3 python3-pip python3-venv python3-dev \
  curl wget git openssh-server rsync \
  android-tools-adb android-tools-fastboot \
  build-essential libffi-dev libgl1 \
  sshpass jq

id -u "${BOT_USER}" >/dev/null 2>&1 || useradd -m -s /bin/bash "${BOT_USER}"

mkdir -p "${LAB_ROOT}"/{app,data,logs,artifacts,releases}
chown -R "${BOT_USER}:${BOT_USER}" "${LAB_ROOT}"

if [[ ! -d "${APP_ROOT}" ]] || [[ -z "$(ls -A "${APP_ROOT}" 2>/dev/null)" ]]; then
  echo "WARN: ${APP_ROOT} empty — 请先在宿主机运行 host_deploy.py --sync"
fi

sudo -u "${BOT_USER}" python3 -m venv "${VENV}"
sudo -u "${BOT_USER}" "${VENV}/bin/pip" install -q --upgrade pip wheel

REQ="${APP_ROOT}/requirements-lab.txt"
if [[ -f "${REQ}" ]]; then
  sudo -u "${BOT_USER}" "${VENV}/bin/pip" install -q -r "${REQ}"
else
  sudo -u "${BOT_USER}" "${VENV}/bin/pip" install -q -r "${APP_ROOT}/requirements-edge.txt"
fi

# vendor airtest 可选（本地 VM 全量）
if [[ -d "${APP_ROOT}/vendor/airtest" ]]; then
  sudo -u "${BOT_USER}" "${VENV}/bin/pip" install -q -e "${APP_ROOT}/vendor/airtest" 2>/dev/null || true
fi
if [[ -d "${APP_ROOT}/vendor/adbutils" ]]; then
  sudo -u "${BOT_USER}" "${VENV}/bin/pip" install -q -e "${APP_ROOT}/vendor/adbutils" 2>/dev/null || true
fi

# APS 兼容符号链接
mkdir -p /home/bot
ln -sfn "${APP_ROOT}" /home/bot/55chat-bot 2>/dev/null || true
ln -sfn "${VENV}" "${APP_ROOT}/.venv" 2>/dev/null || true

# 双 ADB server
sudo -u "${BOT_USER}" adb start-server >/dev/null 2>&1 || true
sudo -u "${BOT_USER}" adb -P 5038 start-server >/dev/null 2>&1 || true
sudo -u "${BOT_USER}" adb -P 5039 start-server >/dev/null 2>&1 || true

cp -f "${APP_ROOT}/local_vm/README-55M.md" "${LAB_ROOT}/README-55M.md" 2>/dev/null || \
  cp -f "${APP_ROOT}/../local_vm/README-55M.md" "${LAB_ROOT}/README-55M.md" 2>/dev/null || true
cp -f "${APP_ROOT}/local_vm/ZONE.json" "${LAB_ROOT}/ZONE.json" 2>/dev/null || \
  cp -f "${APP_ROOT}/../local_vm/ZONE.json" "${LAB_ROOT}/ZONE.json" 2>/dev/null || true

echo "GUEST_BOOTSTRAP_OK lab=${LAB_ROOT} app=${APP_ROOT} venv=${VENV}"
