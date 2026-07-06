# 本地桌面 Runbook（w49-2.9）

与母仓库 `docs/本地桌面测试.md` 同步。

## 架构

| 组件 | 端口 |
|------|------|
| 68助手 WS | **5600** |
| mock Panel | 3000 |
| edge_brain | 8790 |

## 前置

1. 68助手已登录、卡密激活
2. 测试群：**苍井空测试**（ID `492316`）
3. `pip install -r requirements-edge.txt websocket-client`

## 互斥（必须）

启动前停止 `bot_dual_supervisor` / `bot_55chat_daemon`（`BOT_EXECUTOR=ws`）。

## 一键启动

```powershell
cd C:\Users\haijin\Downloads\全自动化机器人
$env:EDGE_BRAIN_JWT_SECRET = 'w49-local-desktop-test'
$env:BOT_55WS_URL = 'ws://127.0.0.1:5600'
$env:BOT_TARGET_GROUP = '苍井空测试'
$env:DESKTOP_GROUP_ID = '492316'
.\.venv\Scripts\python.exe scripts\desktop_local_stack.py
```

健康检查：`scripts\desktop_local_stack.py --check`（含 WS Hello + panel products）

| 项 | 期望 |
|----|------|
| `--check` | `WS_HANDSHAKE=OK` `PANEL_CATALOG=OK` |
| 扣1 | §2.1 模板 |
| 封盘 70s/15s | §5.1 / §5.2 |
| 结算 | 三图 + 新一局 |
| 封盘后下注 | 已封盘无效 |

## 停止

```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  Where-Object { $_.CommandLine -match 'desktop_local|edge_mock|edge_brain' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

勿杀 68助手进程。
