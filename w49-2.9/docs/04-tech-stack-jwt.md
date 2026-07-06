# 技术栈探测与 JWT 依赖（AUTO 2026-07-07）

## 项目技术栈

| 层 | 文件 | 栈 |
|----|------|-----|
| 业务/编排 | `requirements-edge.txt` | Python 3.x |
| Edge API | FastAPI + Uvicorn | HTTP/WS |
| 鉴权 | **PyJWT ≥2.8.0** | HS256 |
| 桌面协议 | `protocol/55ws-client/package.json` | Node + ws |
| 母仓库主 daemon | `bot_55chat_daemon.py` | Python + ADB/u2 |

无 `go.mod`；Go 不在本项目范围。

## JWT 选型结论

| 库 | 判定 |
|----|------|
| **PyJWT** ✅ | Python 生态最主流；2.x 默认算法安全；edge_brain + bot_ops 已用 |
| python-jose | 更重；无额外收益 |
| 自研 | 禁止 |

实现路径：

- `bot_ops/auth/jwt.py` — encode/decode/verify
- `edge_brain/jwt_auth.py` — FastAPI 适配 + `authorization_header()`

## 安装状态（已执行）

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-edge.txt websocket-client
```

| 包 | 版本 |
|----|------|
| PyJWT | 2.13.0 |
| fastapi | 0.139.0 |

测试：`pytest tests/test_jwt_auth.py tests/test_bot_ops_jwt.py` → **8 passed**

## 本地 JWT 环境变量

```powershell
$env:EDGE_BRAIN_JWT_SECRET = 'w49-local-desktop-test'
# 或由 scripts/edge_issue_jwt.py 签发 EDGE_BRAIN_JWT
```
