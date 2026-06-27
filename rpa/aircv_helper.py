"""Airtest aircv 薄封装：ADB 截图 + 模板匹配（无障碍树失效时的 fallback）。"""
from __future__ import annotations

import subprocess

from rpa.bootstrap import ensure_vendor_path


def _adb_screencap_png(serial: str) -> bytes | None:
    try:
        out = subprocess.run(
            ["adb", "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=15,
        )
        if out.returncode == 0 and out.stdout:
            return out.stdout
    except Exception:
        pass
    return None


def match_template_on_serial(
    serial: str,
    template_path: str,
    *,
    threshold: float = 0.8,
) -> tuple[int, int] | None:
    """
    在整屏截图中找模板，返回中心 (x, y)；失败返回 None。
    依赖 vendor/airtest 的 aircv + opencv。
    """
    ensure_vendor_path()
    try:
        import numpy as np  # type: ignore
        from airtest.aircv.template import Template  # type: ignore
    except ImportError:
        return None

    png = _adb_screencap_png(serial)
    if not png:
        return None
    arr = np.frombuffer(png, dtype=np.uint8)
    import cv2  # type: ignore

    screen = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if screen is None:
        return None
    tpl = Template(template_path, threshold=threshold)
    pos = tpl.match_in(screen)
    if not pos:
        return None
    return int(pos[0]), int(pos[1])


def roi_gray_diff(serial: str, y0_ratio: float, y1_ratio: float) -> float | None:
    """聊天区 ROI 帧差（0~1），可替代 daemon 内简易 fingerprint。"""
    ensure_vendor_path()
    png = _adb_screencap_png(serial)
    if not png:
        return None
    try:
        import numpy as np  # type: ignore
        import cv2  # type: ignore
    except ImportError:
        return None
    arr = np.frombuffer(png, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h = img.shape[0]
    y0, y1 = int(h * y0_ratio), int(h * y1_ratio)
    roi = img[y0:y1, :]
    return float(np.mean(roi)) / 255.0
