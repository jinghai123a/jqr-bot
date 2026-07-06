# w49-2.9 · 本地桌面 WS 栈（Tri-Plane Edge）

> **LOCAL ONLY** — 不部署 APS/VPS；仅本机 68助手 + mock panel + edge_brain E2E。  
> 母仓库：`全自动化机器人` · 业务规格：`docs/用户使用.md`

## 本包内容

| 路径 | 说明 |
|------|------|
| [docs/01-tri-plane-architecture.md](./docs/01-tri-plane-architecture.md) | 首席架构方案（预算/并发/安全/压测） |
| [docs/02-protocol-55chat-bot.md](./docs/02-protocol-55chat-bot.md) | 55chat-bot 协议分析与本地对齐 |
| [docs/03-expert-debate-v2.md](./docs/03-expert-debate-v2.md) | 三专家辩论 + V2 落地方案 |
| [docs/04-tech-stack-jwt.md](./docs/04-tech-stack-jwt.md) | 技术栈探测 + JWT 选型 |
| [docs/05-local-desktop-runbook.md](./docs/05-local-desktop-runbook.md) | 本地一键启动与验收 |
| [code/](./code/) | 本次变更代码快照（与母仓库路径对照） |
| [SCOPE.md](./SCOPE.md) | 项目范围：含什么 / 不含什么 |

## 快速启动（母仓库根目录）

```powershell
$env:EDGE_BRAIN_JWT_SECRET = 'w49-local-desktop-test'
$env:BOT_55WS_URL = 'ws://127.0.0.1:5600'
$env:DESKTOP_GROUP_ID = '492316'
.\.venv\Scripts\python.exe scripts\desktop_local_stack.py
```

## 版本

- **w49-2.9** — desktop_ws 模式 + BOT_EXECUTOR 互斥 + desktop-protocol 知识库
- 母仓库 commit 基线：`9de4e03` + 本包剩余 2 文件
