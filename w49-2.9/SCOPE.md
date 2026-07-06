# w49-2.9 范围声明（结束无关文件分析）

## IN SCOPE（本项目管理）

```
w49-2.9/**
config/55m-knowledge/desktop-protocol.json
config/55m-knowledge/executor-matrix.json   # desktop_ws 段
config/55m-knowledge/apis.json              # desktop_protocol 段
config/55m-knowledge/INDEX.md
scripts/desktop_local_stack.py
scripts/desktop_local_announce.py
scripts/edge_knowledge_validate.py
scripts/edge_mock_panel.py
protocol/55ws-client/watch.js
protocol/55ws-client/local_desktop_bot.js
bot_dual_supervisor.py                      # BOT_EXECUTOR=ws 互斥
docs/本地桌面测试.md
edge_brain/ + bot_ops/auth/jwt.py            # JWT 只读依赖
requirements-edge.txt
```

## OUT OF SCOPE（本次不分析、不纳入 w49-2.9 提交）

以下与桌面 WS 本地栈 **无关**，停止跟踪：

- `scripts/vps_force_*.py`、`scripts/vps_migrate_*.py`、`scripts/vps_tunnel_*.py`
- `scripts/vmos_adb_daemon*.py`、`scripts/apply_vmos_console_snapshot.py`
- `scripts/desktop_protocol/install_68_helper*.py`、`deploy_kami_to_vps.py`
- `config/vmos-console-snapshot.json`、`config/vmos-proxy.env.example`
- `data/captures/*.png`、`data/local-panel-state.json`
- `protocol/55ws-client/node_modules/`
- `bot_tunnel/daemon.py`、tunnel 脚本批量改动
- VMOS API client/transport 实验改动

母仓库上述文件保持原状；**w49-2.9 文档与快照不引用它们**。
