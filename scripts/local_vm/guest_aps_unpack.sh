#!/usr/bin/env bash
# APS 上解压 55m 发布包并重启 edge 栈
set -euo pipefail
APS_ROOT="${APS_ROOT:-/home/bot/55chat-bot}"
TARBALL="${1:?usage: guest_aps_unpack.sh /path/55m-xxx.tar.gz}"
BACKUP="${APS_ROOT}.bak.$(date +%Y%m%d%H%M%S)"
TMP="/tmp/55m-unpack.$$"
mkdir -p "${TMP}"
tar -xzf "${TARBALL}" -C "${TMP}"
test -d "${TMP}/app"

if [[ -d "${APS_ROOT}" ]]; then
  cp -a "${APS_ROOT}" "${BACKUP}"
  echo "backup ${BACKUP}"
fi
mkdir -p "${APS_ROOT}"
rsync -a --delete "${TMP}/app/" "${APS_ROOT}/"
chown -R bot:bot "${APS_ROOT}" 2>/dev/null || true

cd "${APS_ROOT}"
if [[ ! -d .venv ]]; then
  sudo -u bot python3 -m venv .venv
fi
sudo -u bot .venv/bin/pip install -q -r requirements-lab.txt 2>/dev/null || \
  sudo -u bot .venv/bin/pip install -q -r requirements-edge.txt

for sh in scripts/edge_brain_start.sh scripts/edge_adb_connect.sh scripts/edge_auto_bootstrap.sh scripts/edge_adb_agent_start.sh; do
  sed -i 's/\r$//' "${APS_ROOT}/${sh}" 2>/dev/null || true
  chmod +x "${APS_ROOT}/${sh}" 2>/dev/null || true
done

bash "${APS_ROOT}/scripts/edge_brain_start.sh" 2>/dev/null || true
bash "${APS_ROOT}/scripts/edge_adb_agent_start.sh" 2>/dev/null || true
rm -rf "${TMP}"
echo "APS_UNPACK_OK ${APS_ROOT}"
