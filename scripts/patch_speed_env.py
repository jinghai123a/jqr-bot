#!/usr/bin/env python3
import re
import json
from pathlib import Path

ROOT = Path("/home/bot/55chat-bot")
p = ROOT / "config" / "bot-start.env"
t = p.read_text(encoding="utf-8") if p.exists() else ""
patch = {
    "BOT_PROBE_ENABLED": "0",
    "BOT_PREWARM": "0",
    "BOT_QUERY_REPLY_COOLDOWN_SEC": "0",
    "BOT_CMD_CLAIM_RACE_SEC": "0.8",
    "BOT_REPLY_COOLDOWN_SEC": "0",
    "BOT_SEND_DEBOUNCE_SEC": "0",
    "BOT_LISTENER_TICK_SEC": "0.03",
    "BOT_LISTENER_IDLE_TICK_SEC": "0.03",
    "BOT_LISTENER_TRUST_SEND": "1",
    "BOT_LISTENER_SEND_ENTER_FIRST": "1",
    "BOT_LISTENER_PURE_PIPE": "1",
    "BOT_LISTENER_BREAK_IM_LINKS": "1",
    "BOT_LISTENER_PINNED_SEND": "1",
    "BOT_LISTENER_SEND_X": "674",
    "BOT_LISTENER_SEND_Y": "1234",
    "BOT_LISTENER_ZERO_NAV": "1",
    "BOT_LISTENER_SEND_TAP_ONLY": "1",
    "BOT_LISTENER_STAY_SANITIZE": "0",
    "BOT_LISTENER_TICK_HIDE_KB": "0",
    "BOT_ADB_HEAL_DURING_SEND": "0",
    "BOT_LISTENER_HIDE_KEYBOARD": "0",
    "BOT_LISTENER_CMDS_PER_TICK": "5",
    "BOT_LISTENER_SEND_FIRE": "1",
    "BOT_UI_COLLECTOR": "1",
    "BOT_LISTENER_BLUE_SEND_POLLS": "1",
    "BOT_LISTENER_SEND_MODE": "adb_b64",
    "BOT_UI_ENGINE": "adb",
    "BOT_LISTENER_UI_ENGINE": "adb",
    "BOT_LISTENER_FAST_SEND": "1",
    "BOT_FAST_DETECT": "0",
    "BOT_LISTENER_FORCE_SCAN_SEC": "0.4",
    "BOT_CLICKER_FAST": "1",
    "BOT_CLICKER_TAP_MS": "80",
    "BOT_CLICKER_IDLE_SEC": "0.05",
    "BOT_CLICKER_STAY_IN_CHAT": "1",
    "BOT_CLICKER_STAY_SEC": "30",
    "BOT_LISTENER_STAY_IN_GROUP": "1",
    "BOT_LISTENER_STAY_RECOVER_SEC": "15",
    "BOT_LISTENER_CHAT_SCROLL_SEC": "2",
    "BOT_CHAT_INPUT_Y_MAX": "1150",
    "BOT_IMG_SEND_MODE": "ui",
    "BOT_IMG_PINNED": "1",
    "BOT_CLICKER_IMG_TAP_ONLY": "1",
    "BOT_CLICK_VERIFY": "1",
    "BOT_IMG_NEWEST_AT": "top",
    "BOT_CLICKER_SEND_IMAGES": "1",
    "BOT_CLICKER_SETTLE": "1",
    "BOT_CLICKER_OPTIONAL": "0",
    "BOT_LOG_WORKERS": "2",
    "BOT_CONTEXT_REFRESH_SEC": "1",
    "BOT_DRAW_FETCH_SEC": "0.35",
    "BOT_SETTLE_LOOP_SEC": "0.15",
    "BOT_ANNOUNCE_LOOP_SEC": "0.15",
    "BOT_SETTLE_SEND_RETRY_SEC": "2",
    "BOT_SETTLE_OPEN_DEFER_MAX_SEC": "180",
    "BOT_LISTENER_FORCE_SCAN_SEC": "0.25",
}
remove_keys = ("BOT_SKIP_BOT_IDS",)
for k in remove_keys:
    t = re.sub("^" + re.escape(k) + "=.*\n?", "", t, flags=re.M)
for k, v in patch.items():
    if re.search("^" + re.escape(k) + "=", t, re.M):
        t = re.sub("^" + re.escape(k) + "=.*", k + "=" + v, t, flags=re.M)
    else:
        t += "\n" + k + "=" + v
p.write_text(t.strip() + "\n", encoding="utf-8")


def env_value(text: str, key: str, default: str) -> str:
    m = re.search("^" + re.escape(key) + r"=(.*)$", text, re.M)
    return (m.group(1).strip() if m else default) or default


def patch_finance_hosts(text: str) -> list[tuple[str, str]]:
    db = ROOT / "finance.db"
    if not db.exists():
        return []
    listener_port = env_value(text, "BOT_LISTENER_ADB_PORT", "60478")
    clicker_port = env_value(text, "BOT_CLICKER_ADB_PORT", "56121")
    desired = {
        env_value(text, "BOT_LISTENER_ID", "bot-4"): f"localhost:{listener_port}",
        "bot-3": f"localhost:{clicker_port}",
    }
    for bid in env_value(text, "BOT_CLICKER_IDS", "bot-3").split(","):
        bid = bid.strip()
        if bid:
            desired[bid] = f"localhost:{clicker_port}"
    data = json.loads(db.read_text(encoding="utf-8"))
    changed: list[tuple[str, str]] = []

    def walk(obj):
        if isinstance(obj, dict):
            bid = obj.get("id")
            if bid in desired and obj.get("adbHost") != desired[bid]:
                obj["adbHost"] = desired[bid]
                changed.append((bid, desired[bid]))
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for val in obj:
                walk(val)

    walk(data)
    if changed:
        db.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


finance_changed = patch_finance_hosts(t)
print("patched", len(patch), "keys; removed", list(remove_keys), "finance", finance_changed)
