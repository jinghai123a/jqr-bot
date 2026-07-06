# 55chat-bot 协议文档快照（a20b484）

> 上游：[yee338024/55chat-bot@a20b484](https://github.com/yee338024/55chat-bot/tree/a20b4841a068bed7031c9afef01672f94cd92990)  
> 本目录为 **VitePress 协议文档站** 摘要；机器可读规格见 `config/55m-knowledge/desktop-protocol.json`。

## 文档索引

| 上游文件 | 内容 |
|----------|------|
| [docs/guide.md](https://github.com/yee338024/55chat-bot/blob/a20b484/docs/guide.md) | 激活、价格表、WS 连接、msgNew 回调样例 |
| [readme.md](https://github.com/yee338024/55chat-bot/blob/a20b484/readme.md) | 握手 Hello、3s 心跳、sendMsg/sendFile、readStatus |
| [docs/msg.md](https://github.com/yee338024/55chat-bot/blob/a20b484/docs/msg.md) | 消息类型表、收发 JSON、发送成败回调 |
| [docs/websocket.md](https://github.com/yee338024/55chat-bot/blob/a20b484/docs/websocket.md) | getGroups、联系人/群 API 代理、sendFile |
| [docs/group.md](https://github.com/yee338024/55chat-bot/blob/a20b484/docs/group.md) | GroupUpdate 枚举、群公告/禁言 |

## a20b484 价格表变更

| 服务 | 月付 | 季付（8折） | 年付（6折） |
|------|------|------------|------------|
| 收/发消息 | 120 U | 300 U | 900 U |

（删除原「仅收取消息 80U」档）

## 本项目差异

| 项 | 文档默认 | 本机实测 |
|----|----------|----------|
| WS 端口 | 5599 | **5600**（68助手 v1.6.8） |
| 助手名 | 55/66助手 | 68助手 |
| 认人字段 | identify 示例有值 | 群聊常 `--`，用 **sendUid** |

## 业务对齐（用户使用）

| 用户使用 | 协议 |
|----------|------|
| 扣1/下注回复 | msgNew + sendMsg |
| 公告三时段 | sendMsg |
| 结算三图 | sendFile×3 |
| ADD/绑 ID | ❌ ADB |
