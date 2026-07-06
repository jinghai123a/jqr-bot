# 68chat-bot 官方协议 · 四页熟通索引

> 在线：[68聊天协议](https://yee338024.github.io/68chat-bot/)  
> 机器全量：`config/55m-knowledge/68chat-protocol.json`  
> 项目绑定：`config/55m-knowledge/desktop-protocol.json`

## 四页文档

| 页 | URL | 核心内容 |
|----|-----|----------|
| **使用说明** | [guide.html](https://yee338024.github.io/68chat-bot/guide.html) | 激活、价格两档、Hello、msgNew 好友/群/禁言/阅后即焚 |
| **WebSocket** | [websocket.html](https://yee338024.github.io/68chat-bot/websocket.html) | sendMsg/sendFile/getGroups/request/restart68 |
| **HTTP** | [http.html](https://yee338024.github.io/68chat-bot/http.html) | `5598`：/sendMsg /sendFile /getGroups /deleteMsg /request |
| **收发送消息** | [msg.html](https://yee338024.github.io/68chat-bot/msg.html) | msgType 表、readStatus ack、custom_msg_id、recall_msg |

## 端口对照

| 通道 | 文档默认 | 本机实测 |
|------|----------|----------|
| WebSocket | 5599 | **5600** |
| HTTP API | **5598** | 待实测（设置页可能 5500） |

## 铁律摘要

1. **custom_msg_id**：11 位、非 0 开头、不重复；sendMsg 在 `data` 内，sendFile 在顶层
2. **ack**：`msgListPropertyUpdate` → `list[].customMsgId` + `readStatus` 1/0
3. **认人**：群聊用 `sendUid`，不用 `identify`（常为 `--`）
4. **只处理**：`msgNew` + `msgType=0` + `isSelf=false` + 目标群
5. **忽略**：`recall_msg`、`groupUpdate`、chatType=50 系统通知

## 本项目主链

```
msgNew(用户) → desktop_local_announce → Panel/模板 → sendMsg/sendFile(WS)
```

HTTP 5598 为官方等价通道，当前未接主执行链，可作探针/备选。

## 业务映射

| 用户使用 | 协议 |
|----------|------|
| 扣1/下注/公告 | WS sendMsg |
| 三图结算 | WS sendFile×3 |
| 扣取消删消息 | HTTP deleteMsg 或 recall_msg 监听 |
| ADD/绑 ID | ADB，协议无 |
