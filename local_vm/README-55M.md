# 55M 本地实验专区（VM 内路径）

VM 内**唯一项目根**：`/opt/55m-lab`

```
/opt/55m-lab/
├── README-55M.md          # 本说明（同步进 VM）
├── ZONE.json              # 版本/清单元数据
├── app/                   # 完整仓库（开源代码 + vendor + probe-android + scripts…）
├── .venv/                 # 统一虚拟环境（全部 pip 模块）
├── data/                  # edge_brain state、运行时数据
├── logs/                  # 全部日志
├── knowledge/             # config/55m-knowledge 镜像（规格速查）
└── releases/              # 打包产物 → 一键上 APS
    └── 55m-YYYYMMDD-HHMMSS.tar.gz
```

## 与 APS 路径对应

| VM 实验 | APS 生产 |
|---|---|
| `/opt/55m-lab/app` | `/home/bot/55chat-bot` |
| `/opt/55m-lab/.venv` | `/home/bot/55chat-bot/.venv` |
| `/opt/55m-lab/releases/*.tar.gz` | 解压覆盖 `/home/bot/55chat-bot` |

`app/config/bot-start.env` 与隧道 env 与 APS 同形；测试通过后 **同一包** 上生产。

## 规格知识库

VM 内：`/opt/55m-lab/knowledge/` ← 同步自 `config/55m-knowledge/`

宿主机校验：`python scripts/edge_knowledge_validate.py`

## 宿主机命令

```powershell
# 1. 挂 D 盘 ISO + 生成 VM
powershell -File scripts\local_vm\setup_vm.ps1

# 2. Ubuntu 装完 → 填 config\local-vm.env 的 VM_HOST

# 3. 全量同步 + 依赖 + edge 栈
python scripts\local_vm\host_deploy.py --all

# 4. 调试通过后打包
python scripts\local_vm\host_pack_deploy.py --pack

# 5. 一键上 APS
python scripts\local_vm\host_pack_deploy.py --deploy-aps
```

## VM 内命令

```bash
sudo bash /opt/55m-lab/app/scripts/local_vm/guest_bootstrap.sh
sudo -u bot bash /opt/55m-lab/app/scripts/local_vm/guest_edge_stack.sh
bash /opt/55m-lab/app/scripts/local_vm/pack_55m_release.sh
```
