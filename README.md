# 企业微信法务自动化平台

平台接收企业微信会话存档消息和资料，执行 OCR 与 AI 结构化，在人工确认案件归属和业务事件后生成付款流水、提醒任务及金山文档视图。平台 SQLite 数据库是唯一事实来源，金山文档可读回、可对账、可重建。

## 核心流程

1. 会话存档消息、媒体和 OCR 结果先进入 `staged`。
2. 单群单案可生成归属候选；无案件或一群多案进入待归属队列。
3. 人工确认资料识别和案件归属，AI 仅提供字段来源、候选和置信度。
4. 已批准事件通过事务型 outbox 执行付款、提醒、状态和金山同步。
5. 金山写入保存文件、工作表、行号和映射版本，并执行读回与每日对账。

历史未归属资料不得按群整批自动回填。付款以不可变流水汇总，支持部分付款、重复凭证拦截、退款/冲正和迁移期初余额。

## 运行组件

- FastAPI 主服务与 PC 管理后台
- 群名自动接入与白名单/黑名单覆盖
- 缴费 9 列跟踪、部分付款和原行状态更新
- 开庭、缴费及分期还款的多档位提醒
- OCR 图片预处理、PDF 多页识别和 AI 法律字段结构化
- 企业微信会话内容存档 sidecar，仅负责接收消息
- OCR sidecar
- wecomapi，唯一生产发送通道
- 金山 MCP
- SQLite WAL 数据库、本机每日备份与恢复工具

Android、CLI、机器人、Webhook 和自建协议账号发送方案已删除。`mock` 发送仅允许自动化测试，生产必须配置 `WECOM_SEND_MODE=wecomapi`。

## 本地启动

```bash
cp .env.example .env
uv sync
alembic upgrade head
uv run uvicorn app.main:app --reload
```

管理后台：`http://127.0.0.1:8000/admin/`

关键配置：

```dotenv
APP_ENV=production
DB_AUTO_CREATE=false
WECOM_SEND_MODE=wecomapi
WECOMAPI_BASE_URL=https://manager.wecomapi.com
WECOMAPI_API_PATH=/wecom/finder/api
WECOMAPI_TOKEN=
WECOMAPI_GUID=
WECOMAPI_CALLBACK_PATH_SECRET=
KDOCS_MODE=real
KDOCS_TRANSPORT=mcp
OCR_PROVIDER=tencent
LEGAL_EXTRACTION_MODE=llm
```

生产密钥只放在服务器 `.env`，不得提交到 Git。回调地址由后台根据 `WECOMAPI_CALLBACK_PATH_SECRET` 显示，并校验路径、GUID、JSON、请求大小和速率。

## 主要 API

- `GET /api/v1/legal/cases/{id}/workspace`
- `POST /api/v1/legal/case-groups`
- `GET /api/v1/legal/attribution-queue`
- `POST /api/v1/legal/attribution-queue/batch-confirm`
- `GET|POST /api/v1/legal/cases/{id}/payments`
- `PATCH /api/v1/legal/cases/{id}/payments/{payment_id}`
- `POST /api/v1/legal/events/{id}/approve|reject|replay`
- `GET /api/v1/legal/groups/{id}/contacts`
- `POST /api/v1/legal/kdocs/reconcile`
- `GET /api/v1/legal/kdocs/reconciliation-results`

## 验证

```bash
pytest -q
node --check app/static/admin/admin.js
DATABASE_URL=sqlite:////tmp/legal-migration.db alembic upgrade head
python scripts/migration_preflight.py /path/to/legal_wecom.db
```

## 备份与发布

`deploy/legal-wecom-backup.timer` 每天运行一致性备份，默认保留 14 天。备份包含 SQLite 在线快照、媒体压缩包、SHA-256 清单和完整性检查。恢复必须使用独立目录先演练。当前不做异地备份，服务器整机损坏时无法依赖本机备份恢复。

维护窗口执行顺序和 AI 原文上下文风险说明见 [docs/operations-refactor.md](docs/operations-refactor.md)。
