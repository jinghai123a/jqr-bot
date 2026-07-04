#!/usr/bin/env bash
# 在 VM 内打 55M 发布包（测试通过后一键上 APS）
set -euo pipefail
LAB_ROOT="${LAB_ROOT:-/opt/55m-lab}"
APP="${LAB_ROOT}/app"
REL="${LAB_ROOT}/releases"
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="55m-${STAMP}"
WORKDIR="${REL}/.build-${NAME}"
OUT="${REL}/${NAME}.tar.gz"
MANIFEST="${WORKDIR}/MANIFEST.json"

mkdir -p "${REL}" "${WORKDIR}"
rm -rf "${WORKDIR}/app"
cp -a "${APP}" "${WORKDIR}/app"

# 剔除运行时垃圾（不上 APS）
find "${WORKDIR}/app" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "${WORKDIR}/app" -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
rm -rf "${WORKDIR}/app/.git" "${WORKDIR}/app/.venv" 2>/dev/null || true
rm -rf "${WORKDIR}/app/probe-android/.gradle" "${WORKDIR}/app/probe-android/app/build" 2>/dev/null || true

python3 - <<PY
import json, os, subprocess, time
app = "${WORKDIR}/app"
files = []
for root, _, names in os.walk(app):
    for n in names:
        p = os.path.join(root, n)
        rel = os.path.relpath(p, "${WORKDIR}")
        files.append({"path": rel.replace("\\\\", "/"), "bytes": os.path.getsize(p)})
manifest = {
    "name": "${NAME}",
    "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "file_count": len(files),
    "aps_unpack_root": "/home/bot/55chat-bot",
    "files_sample": files[:20],
}
with open("${MANIFEST}", "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
PY

tar -czf "${OUT}" -C "${WORKDIR}" app MANIFEST.json
ln -sfn "${OUT}" "${REL}/55m-latest.tar.gz"
rm -rf "${WORKDIR}"
echo "PACK_OK ${OUT}"
ls -lh "${OUT}"
