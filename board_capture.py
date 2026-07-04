# -*- coding: utf-8 -*-
"""控制面板风格走势图 / 交易流水截图（PIL）"""
from __future__ import annotations

import os
import shutil
import time
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore

CAPTURE_DIR = os.environ.get(
    "BOT_CAPTURE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "captures"),
)

_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)


_FONT_WARNED = False


def _clip_cell(text: str, max_chars: int = 36) -> str:
    s = str(text or "")
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _font(size: int) -> Any:
    global _FONT_WARNED
    for path in _FONT_PATHS:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    if not _FONT_WARNED:
        import logging

        logging.getLogger(__name__).error(
            "[FONT] 未找到 CJK 字体，请安装 fonts-noto-cjk / fonts-wqy-microhei"
        )
        _FONT_WARNED = True
    return ImageFont.load_default()


def _ensure_dir() -> str:
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    return CAPTURE_DIR


def _save(img: Image.Image, name: str) -> str:
    path = os.path.join(_ensure_dir(), name)
    img.save(path, format="PNG", optimize=True)
    return path


def _draw_table(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    header_bg: tuple[int, int, int] = (214, 228, 255),
    title_bg: tuple[int, int, int] = (186, 230, 253),
    highlight_row: int | None = 0,
) -> Image.Image:
    if Image is None:
        raise RuntimeError("Pillow 未安装，无法生成截图")
    font = _font(13)
    font_b = _font(14)
    font_title = _font(15)
    pad_x, pad_y = 8, 6
    col_w = [max(_text_w(font, h), 52) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_w):
                col_w[i] = max(col_w[i], _text_w(font, cell) + pad_x * 2)
    row_h = 28
    title_h = 34
    w = sum(col_w) + 2
    h = title_h + row_h * (len(rows) + 1) + 2
    img = Image.new("RGB", (w, h), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    dr.rectangle((0, 0, w, title_h), fill=title_bg)
    dr.text((pad_x, 8), title, fill=(15, 23, 42), font=font_title)
    y = title_h
    dr.rectangle((0, y, w, y + row_h), fill=header_bg)
    x = 0
    for i, head in enumerate(headers):
        dr.rectangle((x, y, x + col_w[i], y + row_h), outline=(203, 213, 225))
        dr.text((x + pad_x, y + pad_y), head, fill=(51, 65, 85), font=font_b)
        x += col_w[i]
    y += row_h
    for ri, row in enumerate(rows):
        bg = (248, 250, 252) if ri % 2 else (255, 255, 255)
        if highlight_row is not None and ri == highlight_row:
            bg = (254, 242, 242)
        x = 0
        for i, cell in enumerate(row):
            dr.rectangle((x, y, x + col_w[i], y + row_h), fill=bg, outline=(226, 232, 240))
            color = (225, 29, 72) if highlight_row is not None and ri == highlight_row and i == 0 else (15, 23, 42)
            dr.text((x + pad_x, y + pad_y), cell, fill=color, font=font)
            x += col_w[i]
        y += row_h
    return img


def _text_w(font: Any, text: str) -> int:
    return int(font.getlength(str(text))) + 16


def upsert_board_rows(
    boards: dict,
    *,
    pc28_row: dict[str, Any],
    mark6_row: dict[str, Any],
    highlight_rid: int,
) -> dict:
    """用本局权威开奖行覆盖 panel 滞后数据，三图期号对齐。"""
    out = dict(boards or {})
    rid = int(highlight_rid)

    def _upsert(key: str, row: dict[str, Any]) -> None:
        rows = [dict(r) for r in (out.get(key) or [])]
        rows = [r for r in rows if int(r.get("roundId") or 0) != rid]
        clean = dict(row)
        clean["roundId"] = rid
        clean["current"] = False
        rows.insert(0, clean)
        out[key] = rows[:15]

    _upsert("pc28", pc28_row)
    _upsert("mark6", mark6_row)
    return out


def patch_trade_flow_draw(flow: dict, *, round_id: int, draw: dict[str, Any]) -> dict:
    """trade-flow API 滞后时用 settle 内存 draw 补齐。"""
    out = dict(flow or {})
    out["period"] = int(round_id)
    dr = dict(out.get("draw") or {})
    n1, n2, n3 = int(draw["n1"]), int(draw["n2"]), int(draw["n3"])
    fr = int(draw.get("final_result", n1 + n2 + n3))
    dr.update({
        "drawn": True,
        "n1": n1,
        "n2": n2,
        "n3": n3,
        "final_result": fr,
        "resultText": f"{n1}+{n2}+{n3}={fr}",
        "dx": draw.get("dx") or ("大" if fr >= 14 else "小"),
        "ds": draw.get("ds") or ("单" if fr % 2 else "双"),
    })
    out["draw"] = dr
    if not out.get("beijingTime"):
        out["beijingTime"] = draw.get("beijingTime") or draw.get("opentime") or ""
    return out


def render_pc28_board_png(boards: dict, *, round_id: int) -> str:
    rows_data = boards.get("pc28") or []
    headers = ["期数", "时间", "结果", "总", "大小", "单双"]
    rows: list[list[str]] = []
    hi: int | None = None
    for i, r in enumerate(rows_data[:15]):
        if int(r.get("roundId", 0)) == round_id:
            hi = i
        mark = "►" if int(r.get("roundId", 0)) == round_id else ""
        rows.append([
            f"{mark}{r.get('roundId', '')}",
            str(r.get("time", "")),
            f"{r.get('n1', '')} {r.get('n2', '')} {r.get('n3', '')}",
            str(r.get("total", "")),
            str(r.get("dx", "")),
            str(r.get("ds", "")),
        ])
    if not rows:
        rows = [["-", "-", "-", "-", "-", "-"]]
        hi = None
    img = _draw_table("PC28 开奖走势", headers, rows, title_bg=(186, 230, 253), header_bg=(224, 242, 254), highlight_row=hi)
    return _save(img, f"pc28_{round_id}_{int(time.time())}.png")


def render_mark6_board_png(boards: dict, *, round_id: int) -> str:
    rows_data = boards.get("mark6") or []
    headers = ["时间", "期号", "特", "生肖", "单双", "大小", "头", "尾", "合", "五行", "波色"]
    rows: list[list[str]] = []
    hi: int | None = None
    for i, r in enumerate(rows_data[:15]):
        if int(r.get("roundId", 0)) == round_id:
            hi = i
        mark = "►" if int(r.get("roundId", 0)) == round_id else ""
        sp = r.get("special")
        te = "保本" if r.get("push") else (str(sp) if sp is not None else "-")
        rows.append([
            str(r.get("time", "")),
            f"{mark}{r.get('roundId', '')}",
            te,
            str(r.get("zodiac", "-")),
            str(r.get("dx", "")),
            str(r.get("da", "")),
            str(r.get("head", "")),
            str(r.get("tail", "")),
            str(r.get("he", "")),
            str(r.get("wuxing", "")),
            str(r.get("wave", "")),
        ])
    if not rows:
        rows = [["-"] * len(headers)]
        hi = None
    img = _draw_table("六合彩走势图", headers, rows, title_bg=(237, 233, 254), header_bg=(237, 233, 254), highlight_row=hi)
    return _save(img, f"mark6_{round_id}_{int(time.time())}.png")


def render_trade_flow_png(flow: dict, *, round_id: int) -> str:
    if Image is None:
        raise RuntimeError("Pillow 未安装，无法生成截图")
    period = flow.get("period", round_id)
    time_label = str(flow.get("beijingTime", "--"))[:11]
    draw = flow.get("draw") or {}
    result_text = draw.get("resultText", "--") if draw.get("drawn") else "--"
    dx_label = draw.get("dx", "-") if draw.get("drawn") else "-"
    ds_label = draw.get("ds", "-") if draw.get("drawn") else "-"
    rows_in = flow.get("rows") or []

    font = _font(12)
    font_b = _font(13)
    width = 820
    header_h = 32
    banner_h = 28
    table_head_h = 28
    row_h = 48
    body_rows = max(len(rows_in), 1)
    height = header_h + banner_h + table_head_h + row_h * body_rows + 12
    img = Image.new("RGB", (width, height), (236, 233, 216))
    dr = ImageDraw.Draw(img)

    seg_w = width // 5
    hdr_pairs = [
        ("时间", time_label), ("期数", str(period)), ("开奖号码", result_text),
        ("大小", dx_label), ("单双", ds_label),
    ]
    for i, (lab, val) in enumerate(hdr_pairs):
        x1 = i * seg_w
        x2 = x1 + seg_w
        dr.rectangle((x1, 0, x2, header_h), fill=(212, 196, 168), outline=(128, 128, 128))
        dr.text((x1 + 6, 4), lab, fill=(0, 0, 0), font=font)
        dr.text((x1 + 6, 16), val, fill=(220, 38, 38), font=font_b)

    y = header_h
    banner = f"第 【{period}】 期，封盘 以上接单，以下无效"
    dr.rectangle((0, y, width, y + banner_h), fill=(240, 240, 240), outline=(128, 128, 128))
    dr.text((max(8, width // 2 - _text_w(font_b, banner) // 2), y + 7), banner, fill=(220, 38, 38), font=font_b)
    y += banner_h

    col_ws = [50, 120, 120, 250, 120, 160]
    heads = ["序号", "玩家昵称", "使用金额", "投注内容", "本期中奖情况", "剩余金额"]
    dr.rectangle((0, y, width, y + table_head_h), fill=(45, 106, 79))
    x = 0
    for i, h in enumerate(heads):
        dr.rectangle((x, y, x + col_ws[i], y + table_head_h), outline=(27, 67, 50))
        dr.text((x + 6, y + 6), h, fill=(255, 255, 255), font=font_b)
        x += col_ws[i]
    y += table_head_h

    if not rows_in:
        dr.rectangle((0, y, width, y + row_h), fill=(245, 245, 245), outline=(128, 128, 128))
        dr.text((width // 2 - 70, y + 16), "暂无本期待交易流水", fill=(100, 116, 139), font=font)
    else:
        for idx, row in enumerate(rows_in):
            bg = (245, 245, 245)
            amt = row.get("amount", 0)
            rem = row.get("remaining", 0)
            contents = row.get("contents") or []
            content = "\n".join(str(c) for c in contents[:5]) if contents else "--"
            win = str(row.get("winStatus") or "待开奖")
            rh = row_h + max(0, min(len(contents), 4) - 1) * 12
            cells = [
                f"{idx + 1:02d}",
                _clip_cell(str(row.get("nickname", "")), 14),
                f"使用【{int(amt) if float(amt) == int(amt) else amt}】",
                _clip_cell(content, 48),
                _clip_cell(win, 12),
                f"剩余【{int(rem) if float(rem) == int(rem) else rem}】",
            ]
            x = 0
            for i, text in enumerate(cells):
                dr.rectangle((x, y, x + col_ws[i], y + rh), fill=bg, outline=(128, 128, 128))
                color = (22, 101, 52) if str(text).startswith("+") else (0, 0, 0)
                if i == 4 and text == "未中":
                    color = (100, 116, 139)
                dr.multiline_text((x + 4, y + 6), str(text)[:80], fill=color, font=font, spacing=2)
                x += col_ws[i]
            y += rh

    return _save(img, f"trade_{round_id}_{int(time.time())}.png")


ARCHIVE_DIR = os.path.join(CAPTURE_DIR, "archive")


def archive_settle_captures(round_id: int, paths: list[str]) -> None:
    """发群前仅生成；发成功后由 ephemeral_burn 删除。此处不再归档占盘。"""
    if os.environ.get("BOT_CAPTURE_ARCHIVE", "0").strip() in ("1", "true", "yes"):
        period_dir = os.path.join(ARCHIVE_DIR, "period", str(round_id))
        os.makedirs(period_dir, exist_ok=True)
        for p in paths:
            if p and os.path.isfile(p):
                shutil.copy2(p, os.path.join(period_dir, os.path.basename(p)))
        _prune_dirs(os.path.join(ARCHIVE_DIR, "period"), keep=1)
        _prune_live_files(CAPTURE_DIR, keep=6)


def _prune_dirs(base: str, *, keep: int) -> None:
    if not os.path.isdir(base):
        return
    dirs = sorted(
        (d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))),
        key=lambda n: int(n) if n.isdigit() else 0,
    )
    for name in dirs[:-keep] if keep > 0 else dirs:
        shutil.rmtree(os.path.join(base, name), ignore_errors=True)


def _prune_live_files(base: str, *, keep: int) -> None:
    if not os.path.isdir(base):
        return
    files = sorted(
        (
            os.path.join(base, f)
            for f in os.listdir(base)
            if f.endswith(".png") and os.path.isfile(os.path.join(base, f))
        ),
        key=os.path.getmtime,
    )
    for path in files[:-keep] if keep > 0 else files:
        try:
            os.remove(path)
        except OSError:
            pass
