# 代码快照 ↔ 母仓库路径

| 快照文件 | 母仓库路径 |
|----------|------------|
| `config__55m-knowledge__desktop-protocol.json` | `config/55m-knowledge/desktop-protocol.json` |
| `config__55m-knowledge__executor-matrix.json` | `config/55m-knowledge/executor-matrix.json` |
| `config__55m-knowledge__apis.json` | `config/55m-knowledge/apis.json` |
| `config__55m-knowledge__panel-catalog.json` | `config/55m-knowledge/panel-catalog.json` |
| `scripts__desktop_local_stack.py` | `scripts/desktop_local_stack.py` |
| `scripts__desktop_local_announce.py` | `scripts/desktop_local_announce.py` |
| `protocol__55ws-client__watch.js` | `protocol/55ws-client/watch.js` |
| `protocol__55ws-client__local_desktop_bot.js` | `protocol/55ws-client/local_desktop_bot.js` |
| `bot_dual_supervisor.py` | `bot_dual_supervisor.py` |

未快照（母仓库直接引用）：

- `scripts/edge_mock_panel.py`（读 `panel-catalog.json`）
- `scripts/edge_knowledge_validate.py`
- `docs/本地桌面测试.md`

基线 commit：`9de4e03` · 本包增量：panel-catalog、ack 重试、getGroups 探针、封盘窗加速轮询
