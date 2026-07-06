# 68chat-bot 协议（官方站熟通）

> **主文档**：[68聊天协议 · WebSocket](https://yee338024.github.io/68chat-bot/websocket.html)  
> 知识库：`config/55m-knowledge/desktop-protocol.json`  
> 旧仓库参考：[55chat-bot@a20b484](https://github.com/yee338024/55chat-bot/commit/a20b4841a068bed7031c9afef01672f94cd92990)

## 68 相对 55 的关键增量

| 项 | 说明 |
|----|------|
| **custom_msg_id** | sendMsg 群 / sendFile **必填**；11 位、不以 0 开头 |
| **ack 匹配** | `msgListPropertyUpdate.list[].customMsgId` |
| **restart68** | 替代 restartApp |
| **recall_msg** | 双向删除回调 |
| **价格** | 收取 60U + 收/发 120U 两档 |

## 连接与收发（同前）

| 步骤 | 内容 |
|------|------|
| WS | 文档 5599；**本机 5600** |
| 握手 | `Hello` + 3s `socketLogin` |
| 收 | `msgNew` → `sendUid` 认人 |
| 发文字 | `sendMsg` + `data.custom_msg_id` |
| 发图 | `sendFile` + 顶层 `custom_msg_id` |
| 拉群 | `getGroups` |

## 本项目已实现

- `desktop_local_announce.py` — 自动 `_gen_custom_msg_id()` + ack 按 customMsgId 匹配
- `protocol/55ws-client/local_desktop_bot.js` — 扣1 回复带 custom_msg_id

## 业务映射

| 用户使用 | 协议 |
|----------|------|
| 扣1/下注/公告 | sendMsg |
| 三图结算 | sendFile×3 |
| ADD/绑 ID | ADB |
