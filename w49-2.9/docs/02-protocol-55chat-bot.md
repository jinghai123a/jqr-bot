# 55chat-bot 协议（a20b484 熟通）

> 上游：[commit a20b484](https://github.com/yee338024/55chat-bot/commit/a20b4841a068bed7031c9afef01672f94cd92990)  
> 知识库：`config/55m-knowledge/desktop-protocol.json`

## 仓库性质

**VitePress 协议文档站**（`55-docs`），非业务机器人。提供 68/55/66 助手 WebSocket JSON 协议。

## 连接

| 步骤 | 内容 |
|------|------|
| 激活 | 助手「设置」中激活卡密 |
| 连接 | `ws://127.0.0.1:5599`（文档）；**本机 5600** |
| 握手 | 收 `{"message":"Hello"}` |
| 心跳 | 每 3s `operator:network` + `socketLogin` |
| 断线 | `socketLoginout`，客户端自动重连 |

## 核心收发

| 方向 | type / operator | 用途 |
|------|-----------------|------|
| 发文字 | `sendMsg` | 公告、扣1、下注回复 |
| 发文件 | `sendFile` | 结算三图（Windows 绝对路径） |
| 收消息 | `msgNew` | 用户指令；`sendUid`→messengerId |
| 发确认 | `msgListPropertyUpdate` | `readStatus` 1=成功 0=失败 |
| 拉群 | `getGroups` | 解析 groupId |

## 群 msgNew 关键字段

```
sendUid, groupId, content, msgType(0=文本), isSelf, groupName, customMsgId
```

- **认人**：`sendUid`（非 `identify`，群内常为 `--`）
- **忽略**：处理 `isSelf=false` 的用户文本
- **回显**：`isSelf=true` 可用于 OUT 检测

## 与用户使用对齐

| 用户使用 | 协议 | 业务层 |
|----------|------|--------|
| 扣1/下注 | msgNew + sendMsg | Panel + handle_command |
| warn/close/open | sendMsg | announce-templates |
| 三图结算 | sendFile×3 | edge_brain settle-bundle |
| ADD/绑 ID | ❌ | ADB 双机 |

## 本项目实现

- `scripts/desktop_local_announce.py` — WS 公告+指令
- `protocol/55ws-client/local_desktop_bot.js` — Node 参考客户端
- `DESKTOP_WS_ACK_OPTIONAL=1` — ack 超时不阻断发送
