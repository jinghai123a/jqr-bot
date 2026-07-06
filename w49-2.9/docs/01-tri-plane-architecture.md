# Tri-Plane Edge 首席架构方案（w49-2.9）

> 痛点锚点：`docs/用户使用.md` §〇 毫秒级三链路 · 千人群 messengerId · 210s/28.run · Panel 账务真相

## 三平面

| 平面 | 组件 | 职责 |
|------|------|------|
| **Control** | Panel :3000 + 28.run | 账户/限额/流水；期号锚点 |
| **Compute** | edge_brain :8790 | timeline、gates、settle-bundle 预渲染 |
| **Delivery** | 68助手 WS（主）+ ADB（冷） | 群聊 IN/OUT；ADD/绑 ID 仅 ADB |

## 热路径 SLA（务实）

| 链路 | 目标 P99 | 实现 |
|------|----------|------|
| 指令回复 | <500ms 本地 / <1.5s 含 Panel | WS msgNew → handle_command → sendMsg |
| 公告 | 进窗 <200ms | CRITICAL 队列 + 250ms 轮询 timeline |
| 结算三图 | 首图 <2s，全套 <5s | 预渲染 bundle + sendFile×3 |

## 预算（月增量 ≤15%）

- 已有：VPS + VMOS×2 + 68助手卡密
- 可选：+1 桌面节点（68助手 热备）— **唯一建议增量**

## 并发（千人群）

- 常态 2–8 msg/s；封盘尖峰 30–80 msg/s
- 单 WS + 单 Python 进程设计上限 ~100 msg/s
- 超出：有界队列 256 + 「系统繁忙」；Panel 读缓存

## 安全

- JWT（PyJWT HS256）保护 edge_brain
- messengerId 只信 WS sendUid
- 下注 fail-closed；幂等 `(groupId, msgId)`
- WS 仅 localhost；Panel 内网 bind

## 执行器互斥

`BOT_EXECUTOR=ws|adb` — 同群同事件禁止双发（见 `bot_dual_supervisor.py`、`desktop_local_stack.py`）

## 压测矩阵

| 场景 | 通过线 |
|------|--------|
| 60 msg/s × 20s | 0 错账；P95 OUT <2s |
| WS 断 45s | 降级 ADB；无重复入账 |
| Panel 500 | 下注拒收；查余额用缓存 |
| 28.run 不可用 | 停下注；不本地跳期 |

## 落地阶段

| 阶段 | 内容 |
|------|------|
| T0 ✅ | desktop_ws + 知识库 + 互斥 |
| T1 | 生产 LISTENER WS 发字 + Panel 缓存 |
| T2 | 结算 WS sendFile；AutoJs6 fallback |
| T3 | 压测脚本 |
| T4 | 68助手热备桌面 |
