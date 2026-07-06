#!/usr/bin/env python3
"""Force-clear stuck Cursor Review checkpoints for 55chat workspace."""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE_ID = "a5e090a5893cdfea52a33d15a8deb804"
CHECKPOINTS = Path(
    os.environ.get("APPDATA", ""),
    "Cursor",
    "User",
    "globalStorage",
    "anysphere.cursor-commits",
    "checkpoints",
)


def main() -> int:
    if not CHECKPOINTS.is_dir():
        print(f"[SKIP] no checkpoints dir: {CHECKPOINTS}")
        return 0

    removed: list[tuple[str, int]] = []
    for d in sorted(CHECKPOINTS.iterdir()):
        mf = d / "metadata.json"
        if not mf.is_file():
            continue
        with mf.open(encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("workspaceId") != WORKSPACE_ID:
            continue
        n = len(meta.get("requestFiles", []))
        shutil.rmtree(d, ignore_errors=True)
        removed.append((d.name, n))

    backup_root = Path(os.environ.get("TEMP", ".")) / f"cursor-review-backup-{datetime.now():%Y%m%d-%H%M%S}"
    backup_root.mkdir(parents=True, exist_ok=True)
    manifest = backup_root / "removed.json"
    manifest.write_text(
        json.dumps({"workspaceId": WORKSPACE_ID, "removed": removed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total = sum(n for _, n in removed)
    print(f"[OK] cleared {len(removed)} checkpoints / {total} review files")
    for cid, n in removed:
        print(f"  - {cid}: {n} files")
    print(f"[OK] manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
