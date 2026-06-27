"""Resolve VMOS padCode from config + API discovery."""
from __future__ import annotations

import re
from typing import Any


def android_major(rom_version: str | int | None) -> int | None:
    if rom_version is None:
        return None
    s = str(rom_version)
    m = re.match(r"(\d+)", s)
    return int(m.group(1)) if m else None


def resolve_pad_code(
    side: str,
    cfg: dict[str, Any],
    pads: list[dict],
    models: dict[str, dict],
) -> str:
    explicit = (cfg.get("pad_code") or "").strip()
    if explicit:
        return explicit

    want_android = cfg.get("match_android")
    want_ip = (cfg.get("match_egress_ip") or "").strip()

    candidates: list[tuple[dict, dict]] = []
    for pad in pads:
        code = str(pad.get("padCode") or pad.get("pad_code") or "")
        if not code:
            continue
        model = models.get(code, {})
        candidates.append((pad, model))

    def score(item: tuple[dict, dict]) -> tuple[int, str]:
        pad, model = item
        code = str(pad.get("padCode") or "")
        s = 0
        rom = android_major(model.get("romVersion") or model.get("androidVersion"))
        if want_android and rom == int(want_android):
            s += 10
        pad_ip = str(pad.get("padIp") or pad.get("deviceIp") or "")
        if want_ip and want_ip in pad_ip:
            s += 5
        return s, code

    ranked = sorted(candidates, key=score, reverse=True)
    if not ranked or score(ranked[0])[0] <= 0:
        raise RuntimeError(
            f"{side}: 未找到匹配云机 (android={want_android}, ip={want_ip})。"
            f"请在 config/vmos-pads.json 填写 pad_code"
        )
    best_score, best_code = score(ranked[0])
    if len(ranked) > 1 and score(ranked[1])[0] == best_score:
        codes = [score(x)[1] for x in ranked if score(x)[0] == best_score]
        raise RuntimeError(f"{side}: 多台云机同分 {codes}，请手动指定 pad_code")
    return best_code
