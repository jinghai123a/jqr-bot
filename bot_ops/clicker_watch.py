"""Left-clicker image send evidence — UI XML counting + log polling."""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .ssh_client import VpsSSH


def parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    return tuple(map(int, m.groups())) if m else None


def count_chat_image_views(root_xml: str) -> int:
    """Count chat-area ImageView bubbles from UI hierarchy XML."""
    try:
        root = ET.fromstring(root_xml)
    except ET.ParseError:
        return 0

    input_bounds: tuple[int, int, int, int] | None = None
    screen_h = 1280
    for node in root.iter("node"):
        cls = node.attrib.get("class") or ""
        if "EditText" in cls:
            b = parse_bounds(node.attrib.get("bounds", ""))
            if b:
                input_bounds = b
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b and b[3] > screen_h:
            screen_h = b[3]

    y_max = (input_bounds[1] - 20) if input_bounds else int(screen_h * 0.82)
    count = 0
    for node in root.iter("node"):
        cls = node.attrib.get("class") or ""
        if "ImageView" not in cls and "Image" not in cls:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[3] > y_max or b[1] < 80:
            continue
        bw, bh = b[2] - b[0], b[3] - b[1]
        if bw >= 100 and bh >= 100 and b[0] < 520:
            count += 1
    return count


def poll_image_send_evidence(
    log_text: str,
    *,
    success_age_sec: int = 600,
    now: datetime | None = None,
) -> dict:
    """Parse bot.log tail for recent image-send success/failure."""
    now = now or datetime.now(timezone.utc)
    ok_lines = [ln for ln in log_text.splitlines() if "批量发图成功" in ln or "左机 UI 发图成功" in ln]
    fail_lines = [
        ln
        for ln in log_text.splitlines()
        if any(x in ln for x in ("批量发图失败", "批量发图未确认", "左机 UI 发图失败", "UI 发图失败"))
    ]
    last_ok = ok_lines[-1] if ok_lines else ""
    last_fail = fail_lines[-1] if fail_lines else ""
    ok_ts = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_ok)
    fail_ts = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_fail)
    log_ok = False
    age_sec: float | None = None
    if ok_ts:
        ts = datetime.strptime(ok_ts.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        age_sec = (now - ts).total_seconds()
        log_ok = age_sec < success_age_sec
        if fail_ts and fail_ts.group(1) > ok_ts.group(1):
            log_ok = False
    return {
        "log_ok": log_ok,
        "last_line": (last_ok or last_fail)[-140:],
        "age_sec": age_sec,
        "has_success": bool(ok_lines),
        "has_failure": bool(fail_lines),
    }


def upload_daemon_assets(ssh: VpsSSH, paths: list[tuple[Path, str]], *, bot_root: str) -> None:
    """Upload local files to VPS bot_root-relative paths."""
    sf = ssh.client.open_sftp()
    try:
        for local, rel in paths:
            if local.is_file():
                sf.put(str(local), f"{bot_root}/{rel}")
    finally:
        sf.close()


def img_round_streak(rids: list[int]) -> int:
    if not rids:
        return 0
    u = sorted(set(rids))
    best = cur = 1
    for i in range(1, len(u)):
        if u[i] == u[i - 1] + 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def img_rounds_from_log(log_text: str) -> list[int]:
    rids: list[int] = []
    pending: int | None = None
    for ln in log_text.splitlines():
        m = re.search(r"结算 rid=(\d+)", ln)
        if m:
            pending = int(m.group(1))
        if "批量发图成功" in ln and pending is not None:
            rids.append(pending)
            pending = None
    return rids


RunFn = Callable[[str, int], str]


def run_image_watch(
    ssh: VpsSSH,
    *,
    config_bot_root: str,
    local_root: Path,
    serial: str,
    group_name: str,
    poll_sec: int = 25,
    max_min: int = 45,
    out_dir: Path | None = None,
    run_fn: RunFn | None = None,
) -> int:
    """Main loop from watch_clicker_images.py."""
    r = config_bot_root
    out = out_dir or (local_root / "logs" / "visual-now")

    def run(cmd: str, t: int = 120) -> str:
        if run_fn:
            return run_fn(cmd, t)
        return ssh.run(cmd, t)

    upload_daemon_assets(
        ssh,
        [
            (local_root / "bot_55chat_daemon.py", "bot_55chat_daemon.py"),
            (local_root / "config" / "pinned-coords.json", "config/pinned-coords.json"),
        ],
        bot_root=r,
    )

    def scroll_chat_bottom() -> None:
        for _ in range(4):
            run(f"adb -s {serial} shell input swipe 360 1100 360 350 220")
            time.sleep(0.3)

    def visual_image_count() -> dict:
        scroll_chat_bottom()
        out_py = run(
            f"""python3 - <<'PY'
import sys
sys.path.insert(0, "{r}")
import bot_55chat_daemon as d
serial = "{serial}"
bot = {{"id": "bot-3", "associatedGroup": {json.dumps(group_name)}}}
root = d.ui_hierarchy(serial)
in_group = d.in_target_group_chat(root, bot, serial)
act = d.is_group_chat_activity(serial)
sh = d.screen_height(root) if root else 0
sw = 720
imgs = []
if root is not None:
    ib = None
    for node in root.iter("node"):
        if "EditText" in (node.attrib.get("class") or ""):
            b = d.parse_bounds(node.attrib.get("bounds", ""))
            if b:
                ib = b
                break
    y_max = (ib[1] - 20) if ib else int(sh * 0.82)
    for node in root.iter("node"):
        cls = node.attrib.get("class") or ""
        if "ImageView" not in cls and "Image" not in cls:
            continue
        b = d.parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[3] > y_max or b[1] < 80:
            continue
        bw, bh = b[2] - b[0], b[3] - b[1]
        if bw >= 100 and bh >= 100 and b[0] < 520:
            imgs.append((bw, bh, b[0], b[1]))
texts = d.collect_ui_texts(root) if root else []
periods = [t for t in texts if "期" in t and "3449" in t]
print("IN_GROUP", in_group, "ACTIVITY", act, "SCREEN", sw, sh)
print("CHAT_IMAGES", len(imgs), imgs[-5:])
print("PERIODS", " | ".join(periods[-4:]))
PY""",
            90,
        )
        info: dict = {"raw": out_py}
        for line in out_py.splitlines():
            if line.startswith("IN_GROUP"):
                parts = line.split()
                info["in_group"] = parts[1] == "True"
                info["activity"] = parts[3] == "True"
            elif line.startswith("CHAT_IMAGES"):
                m = re.search(r"CHAT_IMAGES (\d+)", line)
                if m:
                    info["image_bubbles"] = int(m.group(1))
            elif line.startswith("PERIODS"):
                info["periods"] = line.replace("PERIODS ", "")
        run(f"adb -s {serial} exec-out screencap -p > /tmp/clicker_watch.png")
        out.mkdir(parents=True, exist_ok=True)
        ssh.sftp_get("/tmp/clicker_watch.png", str(out / "clicker_watch.png"))
        return info

    deadline = time.time() + max_min * 60
    last_probe = 0.0
    probe_count = 0

    while time.time() < deadline:
        run(
            f"""python3 - <<'PY'
import os, sys
sys.path.insert(0, "{r}")
os.chdir("{r}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="{serial}"
bot={{"id":"bot-3","associatedGroup":{json.dumps(group_name)}}}
if not d.in_target_group_chat(d.ui_hierarchy(serial), bot, serial):
    d.ensure_clicker_in_group(serial, bot, reason="img-watch")
PY""",
            90,
        )
        vis = visual_image_count()
        log_raw = run(f"tail -n 5000 {r}/logs/bot.log")
        evidence = poll_image_send_evidence(log_raw)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(
            f"[{ts}] bubbles={vis.get('image_bubbles',0)} in_group={vis.get('in_group')} "
            f"log_ok={evidence['log_ok']} periods={vis.get('periods','')[:60]}",
            flush=True,
        )
        bubbles = vis.get("image_bubbles", 0)
        if vis.get("in_group") and bubbles >= 1 and evidence["log_ok"]:
            result = {
                "ok": True,
                "image_bubbles": bubbles,
                "log": evidence["last_line"],
                "utc": datetime.now(timezone.utc).isoformat(),
            }
            (local_root / "logs" / "clicker_img_ok.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("DONE", json.dumps(result, ensure_ascii=False))
            return 0

        if bubbles < 1 and time.time() - last_probe > 120 and probe_count < 3:
            probe_out = run(
                f"""python3 - <<'PY'
import glob, os, sys
sys.path.insert(0, "{r}")
os.chdir("{r}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="{serial}"
bot={{"id":"bot-3","associatedGroup":{json.dumps(group_name)}}}
paths = sorted(glob.glob("data/captures/*.png"), key=os.path.getmtime)
if not paths:
    print("NO_CAPTURE"); raise SystemExit(2)
p = paths[-1]
if not d.in_target_group_chat(d.ui_hierarchy(serial), bot, serial):
    d.ensure_clicker_in_group(serial, bot, reason="probe-img")
snap = d.ui_snapshot(serial, chat=True)
ix = snap.input_xy
sy = snap.inbar_send or snap.keyboard_send
ok = d.send_chat_image(serial, bot, p, ix, sy, {{}}, group_ok=True)
print("PROBE_IMG_OK" if ok else "PROBE_IMG_FAIL", p)
PY""",
                180,
            )
            print(probe_out.strip(), flush=True)
            last_probe = time.time()
            probe_count += 1
            time.sleep(12)
            continue

        time.sleep(poll_sec)

    print(json.dumps({"ok": False, "reason": "timeout"}, ensure_ascii=False))
    return 1


def run_consecutive_rounds_watch(
    ssh: VpsSSH,
    *,
    config_bot_root: str,
    local_root: Path,
    serial: str,
    group_name: str,
    need: int = 2,
    poll_sec: int = 25,
    max_min: int = 90,
) -> int:
    """From watch_clicker_2rounds.py — consecutive img rounds + visible chat images."""
    r = config_bot_root
    upload_daemon_assets(
        ssh,
        [
            (local_root / "bot_55chat_daemon.py", "bot_55chat_daemon.py"),
            (local_root / "config" / "pinned-coords.json", "config/pinned-coords.json"),
        ],
        bot_root=r,
    )

    def scroll_bottom() -> None:
        for _ in range(4):
            ssh.run(f"adb -s {serial} shell input swipe 360 1100 360 350 220")
            time.sleep(0.25)

    def chat_images() -> int:
        scroll_bottom()
        out = ssh.run(
            f"""python3 - <<'PY'
import sys
sys.path.insert(0, "{r}")
import bot_55chat_daemon as d
serial="{serial}"
bot={{"id":"bot-3","associatedGroup":{json.dumps(group_name)}}}
root=d.ui_hierarchy(serial)
ib=None
if root:
    for node in root.iter("node"):
        if "EditText" in (node.attrib.get("class") or ""):
            b=d.parse_bounds(node.attrib.get("bounds",""))
            if b: ib=b; break
n=0
if root and ib:
    y_max=ib[1]-16
    for node in root.iter("node"):
        if "ImageView" not in (node.attrib.get("class") or ""): continue
        b=d.parse_bounds(node.attrib.get("bounds",""))
        if not b or b[3]>y_max or b[1]<80: continue
        bw,bh=b[2]-b[0],b[3]-b[1]
        if bw>=100 and bh>=100: n+=1
print(n)
PY""",
            60,
        )
        try:
            return int(out.strip().splitlines()[-1])
        except ValueError:
            return 0

    deadline = time.time() + max_min * 60
    print(f"[watch-img] 目标连续 {need} 期发图成功 + 群里可见图片", flush=True)

    while time.time() < deadline:
        imgs = chat_images()
        log_raw = ssh.run(f"tail -n 6000 {r}/logs/bot.log")
        rids = img_rounds_from_log(log_raw)
        st = img_round_streak(rids)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] chat_images={imgs} img_rounds={rids[-5:]} streak={st}", flush=True)

        if st >= need and imgs >= 1:
            out = {
                "ok": True,
                "streak": st,
                "rounds": rids[-need:],
                "chat_images": imgs,
                "utc": datetime.now(timezone.utc).isoformat(),
            }
            fname = f"clicker_img_{need}rounds.json"
            (local_root / "logs" / fname).write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("DONE", json.dumps(out, ensure_ascii=False))
            return 0
        time.sleep(poll_sec)

    log_raw = ssh.run(f"tail -n 6000 {r}/logs/bot.log")
    print(json.dumps({"ok": False, "streak": img_round_streak(img_rounds_from_log(log_raw))}))
    return 1
