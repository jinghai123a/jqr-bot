# 三专家辩论 → V2 落地方案

## 独立方案摘要

| 专家 | 方向 |
|------|------|
| A 协议工程师 | WS 为唯一热路径执行器 |
| B 平台架构师 | Panel + 28.run 唯一真相，业务不下沉 WS |
| C 运维工程师 | WS 仅本地冒烟；生产双机 ADB；禁止双发 |

## V2 收敛

**分层混合 + 执行器互斥 + 诚实验收边界**

- P0 ✅ 知识库 + `BOT_EXECUTOR=ws` + stack 冲突检测
- P1 群聊 E2E（扣1/封盘/三图）— **OUT 时间戳验收**
- P1.5 mock panel 导入真实 products/combo-rules
- P2 getGroups 探针 + readStatus 重试
- P3 生产 VPS 68助手 PoC（未 PoC 禁止切流）

## 明确不测（P1）

添加、绑定123456、上分/下分面板审批 → ADB backlog

## 已实现代码

见 `w49-2.9/code/` 快照与 `SCOPE.md`
