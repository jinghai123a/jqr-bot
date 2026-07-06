# 68chat-bot 官方协议 · 五页 + On this page 全熟通

> 在线：[68聊天协议](https://yee338024.github.io/68chat-bot/)  
> 机器全量：`config/55m-knowledge/68chat-protocol.json` → **`on_this_page`** 字段  
> 项目绑定：`config/55m-knowledge/desktop-protocol.json`

## 五页（侧栏「群组事件」= 第 5 页）

| # | 页 | URL |
|---|-----|-----|
| 1 | 使用说明 | [guide.html](https://yee338024.github.io/68chat-bot/guide.html) |
| 2 | WebSocket | [websocket.html](https://yee338024.github.io/68chat-bot/websocket.html) |
| 3 | HTTP | [http.html](https://yee338024.github.io/68chat-bot/http.html) |
| 4 | 收发送消息 | [msg.html](https://yee338024.github.io/68chat-bot/msg.html) |
| 5 | 群组事件 | [group.html](https://yee338024.github.io/68chat-bot/group.html) |

## On this page 子节清单

### guide.html（6 顶栏 + 回调 6 子节）

激活软件 · 价格表 · 联系客服 · 连接 websocket(Hello) · **68消息回调** → 好友/群聊/groupUpdate/群禁言/阅后即焚开/关

### websocket.html（20 节）

UserInfo · ContactsList · 报错测试 · getGroups · sendMsg 好友/群 · GroupMemberList · ContactsDetail · ContactsApplyList · 在线状态 · GroupDetail · sendFile · getApiUrl · 多行文本 · 更新群简介(op12) · **群公告通知(chatType8)** · 群禁言(op11) · 禁言通知(chatType50) · 成员禁言 · restart68

### http.html（17 节）

同上能力走 `5598`；独有 **deleteMsg**（`isRemoteDeletion` true=双向删）

### msg.html（类型表 + 发送 4 + 收取 5）

**发送**：ack(readStatus) · 好友 sendMsg · 群 sendMsg+custom_msg_id · sendFile 顶层 custom_msg_id  
**收取**：文字(0) · 图片(1) `url||thumb||size||0` · recall_msg · 文件(7) `url||name||size` · 骰子(12) `点||随机数`

### group.html（2 节）

**GroupUpdate 枚举 0–18**（NOTICE=12 SHUTUP=11 …） · 更新群简介两步（API 不自动通知 → 须再发 chatType=8）

## 铁律

| 项 | 值 |
|----|-----|
| custom_msg_id | 11 位、非 0 开头；sendMsg→data 内；sendFile→顶层 |
| ack | msgListPropertyUpdate + customMsgId + readStatus 1/0 |
| 认人 | sendUid（非 identify） |
| 本机 WS | 5600（文档 5599） |
| 群公告 | GroupUpdate op12 **+** sendMsg chatType8（缺一不可） |

## 本项目

主链 `desktop_local_announce.py`；只处理 msgType 0/1；忽略 recall_msg/groupUpdate/chatType50。
