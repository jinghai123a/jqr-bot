"""55M 群聊界面硬特征（W49 截图归档）。"""
from __future__ import annotations

import re

GROUP_HEADER_RE = re.compile(r"^.+\(\d+\)$")
COMPOSER_MARKERS = ("输入消息", "Enter message")
MESSAGE_LIST_MARKERS = ("搜索", "Search")
BOTTOM_TAB_MARKERS = ("消息", "Chats", "会话", "通讯录", "通话", "我")

EXIT_APP_MARKERS = (
    "再按一次退出",
    "再按一次退出程序",
    "Press again to exit",
    "press back again to exit",
)

UPGRADE_POPUP_MARKERS = ("发现新版本", "立即升级")

NAV_DRAWER_MARKERS = ("打开侧拉抽屉", "Close navigation drawer", "Open navigation drawer")


def matches_group_header(title: str, configured_group: str = "") -> bool:
    """抬头「苍井空测试 (9)」≈ configured「苍井空测试」。"""
    t = (title or "").strip()
    g = (configured_group or "").strip()
    if not t:
        return False
    if not g:
        return bool(GROUP_HEADER_RE.match(t))
    if t == g or g in t:
        return True
    base = t.split("(")[0].strip()
    return base == g or g in base


def ui_texts_show_exit_warning(texts: list[str]) -> bool:
    blob = " ".join(texts)
    low = blob.lower()
    return any(m in blob or m.lower() in low for m in EXIT_APP_MARKERS)


def ui_texts_show_upgrade_popup(texts: list[str]) -> bool:
    blob = " ".join(texts)
    return all(m in blob for m in UPGRADE_POPUP_MARKERS)


def ui_texts_show_nav_drawer(texts: list[str]) -> bool:
    return any(m in t for t in texts for m in NAV_DRAWER_MARKERS)


def is_target_group_surface(
    texts: list[str],
    header_texts: list[str],
    *,
    configured_group: str = "",
) -> bool:
    """
    群聊页（非消息列表、非退群）：
    - 顶栏群名含 (人数)
    - 底部有「输入消息」
    - 非消息列表（无顶栏「搜索」+ 底栏 Tab 主导）
    """
    has_composer = any(t in COMPOSER_MARKERS for t in texts)
    if not has_composer:
        return False
    headers = [h.strip() for h in header_texts if h and h.strip()]
    group_hit = any(
        matches_group_header(h, configured_group) or GROUP_HEADER_RE.match(h)
        for h in headers
    )
    if not group_hit and configured_group:
        group_hit = any(
            matches_group_header(t, configured_group)
            for t in texts
            if GROUP_HEADER_RE.match(t.strip())
        )
    if not group_hit:
        return False
    # 消息列表：大标题「消息」+ 搜索框；群聊顶栏是群名
    if any(t in MESSAGE_LIST_MARKERS for t in texts):
        if any(h in BOTTOM_TAB_MARKERS[:3] for h in headers):
            return False
    return True


def is_message_list_surface(texts: list[str], header_texts: list[str]) -> bool:
    if not any(t in BOTTOM_TAB_MARKERS[:1] for t in texts):
        return False
    if any(t in MESSAGE_LIST_MARKERS for t in texts):
        return True
    return any(h in BOTTOM_TAB_MARKERS[:1] for h in header_texts)
