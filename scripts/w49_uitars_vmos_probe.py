#!/usr/bin/env python3
"""
UI-TARS 风格本机窗口探测（operator.screenshot 胶水层，非 APS 热路径）。

在 Windows 上截取 VMOS 控制台/云机窗口，供 W49 肉眼对照群聊与断点排查。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "artifacts" / "uitars-vmos"
TITLE_KEYS = ("vmos", "v03", "云机", "vmoscloud", "55m", "苍井")


def _ensure_deps() -> None:
    for pkg in ("mss", "pygetwindow", "Pillow"):
        try:
            __import__(pkg if pkg != "Pillow" else "PIL")
        except ImportError:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", pkg],
                timeout=120,
            )


def _find_windows() -> list:
    import pygetwindow as gw

    hits = []
    seen: set[str] = set()
    for w in gw.getAllWindows():
        title = (w.title or "").strip()
        if not title or title in seen:
            continue
        low = title.lower()
        if any(k in low for k in TITLE_KEYS):
            seen.add(title)
            hits.append(w)
    return hits


def _capture_region(left: int, top: int, width: int, height: int, out: Path) -> bool:
    import mss
    from PIL import Image

    if width < 40 or height < 40:
        return False
    with mss.MSS() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
    return out.is_file() and out.stat().st_size > 500


def main() -> int:
    if sys.platform != "win32":
        print("SKIP: w49_uitars_vmos_probe 仅 Windows 本机", flush=True)
        return 0

    _ensure_deps()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    manifest: dict = {"ts_utc": ts, "windows": [], "captures": []}

    wins = _find_windows()
    if not wins:
        import mss
        from PIL import Image

        full = OUT_DIR / f"desktop_{ts}.png"
        with mss.MSS() as sct:
            mon = sct.monitors[0]
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.save(full)
        manifest["captures"].append({"kind": "desktop_fallback", "path": str(full)})
        print(f"no VMOS window — saved desktop {full}", flush=True)
    else:
        for i, w in enumerate(wins):
            try:
                if w.isMinimized:
                    w.restore()
            except Exception:
                pass
            info = {
                "index": i,
                "title": w.title,
                "left": w.left,
                "top": w.top,
                "width": w.width,
                "height": w.height,
            }
            manifest["windows"].append(info)
            out = OUT_DIR / f"vmos_{i}_{ts}.png"
            ok = _capture_region(w.left, w.top, w.width, w.height, out)
            if ok:
                manifest["captures"].append({"kind": "window", "title": w.title, "path": str(out)})
                print(f"capture ok: {w.title!r} -> {out}", flush=True)
            else:
                print(f"capture skip: {w.title!r}", flush=True)

    manifest_path = OUT_DIR / f"manifest_{ts}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest: {manifest_path}", flush=True)
    return 0 if manifest["captures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
