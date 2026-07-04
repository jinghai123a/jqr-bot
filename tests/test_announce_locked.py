"""公告模板锁定（不 import daemon，Windows 无 fcntl）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "config" / "55m-knowledge" / "announce-templates.json"


def _apply_locked(raw: dict | None) -> dict[str, str]:
  """与 bot_55chat_daemon.merge_settings 锁定段一致。"""
  data = json.loads(KB.read_text(encoding="utf-8"))
  tpls = data.get("templates") or {}
  out = dict(raw or {})
  if os.environ.get("BOT_ANNOUNCE_LOCKED", "1").lower() in ("1", "true", "yes"):
    if (tpls.get("open") or {}).get("template"):
      out["openAnnounceTemplate"] = str(tpls["open"]["template"])
  return out


def test_locked_open_template_overrides_panel():
  os.environ["BOT_ANNOUNCE_LOCKED"] = "1"
  dirty = {"openAnnounceTemplate": "set 【{round_id}期】 新的一局开始 —— 扣1 查询余额编号"}
  out = _apply_locked(dirty)
  tpl = out["openAnnounceTemplate"]
  assert "扣1 查余额编号" in tpl
  assert tpl.startswith("【")
  assert "查询余额编号set" not in tpl.replace(" ", "")


def test_announce_templates_forbidden_edit():
  data = json.loads(KB.read_text(encoding="utf-8"))
  for key in ("warn", "close", "open"):
    assert data["templates"][key].get("forbidden_edit") is True
