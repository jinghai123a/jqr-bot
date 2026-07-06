# 55M 知识库索引

> **最高标准**：**`docs/用户使用.md`**（毫秒级回复/公告/结算 + 指令/玩法/时序）。  
> `docs/固定文档.md` 禁止/铁律/禁改 **已解除**，仅历史参考。

## 文件地图

| 文件 | 内容 |
|------|------|
| [oss-stack.json](./oss-stack.json) | 永久开源栈：仓库、星标、文档、用法 |
| [apis.json](./apis.json) | Edge Brain / Panel / Gateway / 28.run / VMOS API |
| [apks.json](./apks.json) | AutoJs6、Probe、ADB Keyboard |
| [coords.json](./coords.json) | 720×1280 钉死坐标 + 发图链 |
| [announce-templates.json](./announce-templates.json) | warn / close / open 正文 + 时序 |
| [chat-commands.json](./chat-commands.json) | 群内指令、下注格式、ADD |
| [control-plane.json](./control-plane.json) | 端口、进程、VM 专区、APS 路径 |
| [ui-pages.json](./ui-pages.json) | 55Messenger 页面地图 |
| [edge-events.json](./edge-events.json) | 事件门控与 API 调用序 |
| [desktop-protocol.json](./desktop-protocol.json) | 68助手 WS 协议（55chat-bot 文档 + 本机扩展） |
| [executor-matrix.json](./executor-matrix.json) | 执行器模式 desktop_ws / edge_124 / dual_supervisor |
| [panel-catalog.json](./panel-catalog.json) | mock panel products/combo-rules（对齐用户使用 §3） |

## 宿主机 → VM

知识库随全量同步进 `/opt/55m-lab/app/config/55m-knowledge/`。

```powershell
python scripts/local_vm/host_deploy.py --sync
```

## 改规格流程

1. 改对应 JSON + 跑 `pytest tests/test_edge_brain.py`
2. 本地 VM E2E
3. `host_pack_deploy.py --deploy-aps`
