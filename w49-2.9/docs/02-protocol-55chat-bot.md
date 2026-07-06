# 55chat-bot 协议分析（a20b484）

> 来源：https://github.com/yee338024/55chat-bot/tree/a20b4841a068bed7031c9afef01672f94cd92990

## 结论

该仓库是 **VitePress 协议文档站**（package 名 `55-docs`），不是业务机器人。

## 协议能力

| 能力 | 格式 |
|------|------|
| 握手 | `{"message":"Hello"}` |
| 心跳 | 3s `networkStatusType: socketLogin` |
| 收消息 | `operator: msgNew`（含 sendUid/groupId） |
| 发文字 | `type: sendMsg` |
| 发文件 | `type: sendFile`（Windows 绝对路径） |
| 发送确认 | `msgListPropertyUpdate` readStatus 0/1 |

## 本机扩展（未入官方 readme）

- `getGroups` — 68助手 v1.6.8 可用
- 默认端口 **5600**（文档写 5599）

## 与用户使用对齐

| 用户使用 | 协议层 | 业务层 |
|----------|--------|--------|
| 扣1/下注 | msgNew + sendMsg | handle_command + Panel |
| 公告 | sendMsg | w49_core timing + 模板 |
| 三图结算 | sendFile×3 | edge_brain settle-bundle |
| ADD/绑 ID | ❌ | ADB UI |

知识库：`config/55m-knowledge/desktop-protocol.json`
