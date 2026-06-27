# 开源 RPA / 移动 UI 自动化（vendored）

本目录为 **只读参考 + 可选 import**，不替代现有 `bot_55chat_daemon.py` 双脑编排。
55Chat **无消息 API**，入站仍靠读屏；这些项目补 **图像识别 / ADB 工具链**，不是 IM 回调。

## 已复制（`git clone --depth 1`）

| 目录 | 项目 | Stars 量级 | License | 为何选它 |
|------|------|-----------|---------|----------|
| `airtest/` | [AirtestProject/Airtest](https://github.com/AirtestProject/Airtest) v1.4.3 | ~9k | Apache-2.0 | 网易系，**图像模板匹配**（`aircv`），无障碍树读不到气泡时的 fallback |
| `adbutils/` | [openatx/adbutils](https://github.com/openatx/adbutils) | ~1k+ | MIT | OpenATX 生态，**ADB 截图/shell/sync**；u2 底层同款 |
| `uiautomator2-ref/` | [openatx/uiautomator2](https://github.com/openatx/uiautomator2) | ~7k+ | Apache-2.0 | **对照源码**（daemon 已 pip 依赖 u2，此处供读实现） |

## 未复制（不适合本仓库硬拷）

| 项目 | 原因 |
|------|------|
| **Appium** | 需 Appium Server + WebDriver 会话；双脑已是 ADB+u2 直连，叠一层反而慢 |
| **Maestro** | YAML 测试流，面向 CI E2E，不是 7×24 群内机器人 |
| **OpenRPA / TagUI** | 桌面/Web RPA，与 Android 云机栈无关 |
| **Espresso/XCUITest** | 需插桩进 APK，55M 不可改包 |

## 用法

```python
# 项目根目录
from rpa.bootstrap import ensure_vendor_path
ensure_vendor_path()

# 图像模板（需 opencv + numpy，见 requirements-vendor.txt）
from rpa.aircv_helper import match_template_on_serial
pos = match_template_on_serial("127.0.0.1:60478", "assets/send_btn.png")
```

VPS 安装可选依赖：

```bash
pip install -r requirements-vendor.txt
export BOT_RPA_VENDOR=1   # 启用 vendor 路径（见 rpa/bootstrap.py）
```

## 许可

各子目录保留原仓库 LICENSE；修改或再分发请遵守 Apache-2.0 / MIT 条款。
