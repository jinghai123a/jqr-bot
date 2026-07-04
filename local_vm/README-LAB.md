# W49 本地 VMware 实验机（APS 镜像）

按 `Desktop\123.txt` 与 APS `46.183.27.174` 同构，在 **本机 VM** 里跑 edge 全栈，云机隧道从 VM 出，不占用 APS。

## 宿主机规格（已探测）

| 项 | 值 | VM 分配 |
|---|---|---|
| CPU | 6 核 / 12 线程 | **4 核**（123.txt 50%） |
| 内存 | 16 GB | **4 GB**（留 ≥8GB 给 Win） |
| 网络 | — | **NAT** |
| 磁盘 | — | **40 GB 拆分、动态** |

## 一次性：创建虚拟机

```powershell
cd 全自动化机器人
powershell -ExecutionPolicy Bypass -File scripts\local_vm\setup_vm.ps1
```

1. 用 VMware 打开 `C:\Users\Public\虚拟机\w49-edge-lab\w49-edge-lab.vmx`
2. 安装 **Ubuntu Server 22.04 LTS**（用户 `bot`，勾选 OpenSSH）
3. 装完在 VM 里记 `ip a` 的地址，写入 `config/local-vm.env` 的 `VM_HOST`

## 部署 edge 全栈到 VM

```powershell
python scripts/local_vm/host_deploy.py --bootstrap
python scripts/local_vm/host_deploy.py --edge-up
```

## VM 内验收

```bash
curl -s http://127.0.0.1:8790/health
bash /home/bot/55chat-bot/scripts/vps_post_task_tunnel_verify.sh
tail -f /home/bot/55chat-bot/logs/edge-adb-agent.log
```

## 本地 E2E 通过后上 APS

```powershell
python scripts/edge_deploy_aps.py
```
