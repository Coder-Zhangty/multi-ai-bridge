# Multi-AI Bridge

[简体中文](#简体中文) · [English](#english)

## 简体中文

Multi-AI Bridge 是一个本地 FastAPI 服务，为多个 AI 聊天平台提供统一的流式聊天接口。它可使用已配置的供应商 API，或通过 Playwright 和 Chromium 管理浏览器会话。每个平台可独立选择调用方式。

### 本地运行

需要 Python 3.11+。如仅使用供应商 API，可跳过 Chromium 安装。

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

在 `.env` 中填写对应的供应商 API Key。使用浏览器模式时，可运行 `python scripts/login_deepseek.py` 手动登录 DeepSeek。已有旧版账号文件时，可用 `python scripts/migrate_accounts.py --source /path/to/accounts.json` 导入。

| 接口 | 用途 |
|---|---|
| `POST /v1/chat` | 发送含 `platform` 和 `message` 的 JSON，接收 SSE 流 |
| `GET /v1/health` | 查看平台和实例池状态 |
| `GET /api/health` | 查看服务状态 |

如配置了服务端 `API_KEY`，调用聊天和详细健康接口时需发送 `Authorization: Bearer <API_KEY>` 请求头。账号数据库、加密密钥和 Chromium 配置保存在源码目录外。Windows 默认数据目录是 `%LOCALAPPDATA%\AuroraBridge`。

## English

Multi-AI Bridge is a local FastAPI service that provides a common streaming chat interface across several AI platforms. It uses configured provider APIs or manages Chromium sessions through Playwright. You can select the connection mode for each platform.

### Run locally

Use Python 3.11+ and the commands above. Chromium is optional in API-only setups. Add the relevant provider keys to `.env`. For browser mode, run `python scripts/login_deepseek.py` to sign in to DeepSeek manually. To import legacy account data, run `python scripts/migrate_accounts.py --source /path/to/accounts.json`.

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat` | Accepts JSON with `platform` and `message` and streams SSE events |
| `GET /v1/health` | Shows platform and instance pool status |
| `GET /api/health` | Reports basic service health |

If the service has an `API_KEY`, send it as an `Authorization: Bearer <API_KEY>` header for chat and detailed health requests. The account database, encryption key and Chromium profiles live outside the source tree. On Windows, the default data directory is `%LOCALAPPDATA%\AuroraBridge`.
