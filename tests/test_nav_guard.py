from bot_ops.nav_guard import (
    is_message_list_surface,
    is_target_group_surface,
    matches_group_header,
    ui_texts_show_exit_warning,
    ui_texts_show_upgrade_popup,
)


def test_group_header_with_member_count():
    assert matches_group_header("苍井空测试 (9)", "苍井空测试")


def test_target_group_surface_w49_screenshot():
    texts = [
        "苍井空测试 (9)",
        "输入消息",
        "【3452654期】 新的一局开始",
    ]
    headers = ["苍井空测试 (9)"]
    assert is_target_group_surface(texts, headers, configured_group="苍井空测试")


def test_message_list_not_target_group():
    texts = ["消息", "搜索", "苍井空测试", "通讯录", "通话", "我"]
    headers = ["消息"]
    assert not is_target_group_surface(texts, headers, configured_group="苍井空测试")
    assert is_message_list_surface(texts, headers)


def test_exit_warning_detected():
    assert ui_texts_show_exit_warning(["再按一次退出程序"])


def test_upgrade_popup_detected():
    assert ui_texts_show_upgrade_popup(["发现新版本 V.6.7.0", "立即升级", "消息"])
