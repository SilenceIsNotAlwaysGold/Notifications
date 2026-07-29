# 企业微信法务自动化平台

平台接收企业微信会话存档消息和资料，执行 OCR 与 AI 分类、结构化和上下文判断，再进入对应业务待办。平台 SQLite 数据库是唯一事实来源，金山文档是可读回、可对账、可重建的外部业务台账。

## 核心流程

1. 群先配置为“正式处理”“仅采集”“待确认”或“停用”；测试与需求沟通群必须使用“仅采集”。
2. 正式群中的图片、PDF 和文件先 OCR，再结合相邻群聊由 AI 分到四条独立业务线：缴费通知、执行文书、开庭传票、还款协议/回款凭证。
3. 执行文书、传票、还款协议和回款凭证进入各自人工待办。AI 只预填字段、来源和候选关联；复核前不记账、不提醒、不写金山。
4. 缴费通知不要求案件匹配，直接以原消息所在群和发送人为跟进对象；收到明确付款文字或付款凭证后关闭，未闭环时按规则提醒。
5. 已批准资料通过事务型 outbox 上传原文件、写入对应金山子表并保存工作表、行号、映射版本和读回结果。

企业微信群不是案件容器，同一个群可以同时沟通多个案件。案号和历史案件归属只用于旧数据兼容，不能作为传票、执行文书、缴费或还款流程的前置条件。付款和回款以已批准凭证为依据，重复文件不重复计入；还款协议按分期计划汇总已还、剩余、逾期和结清状态。

## 运行组件

- FastAPI 主服务与 PC 管理后台
- 群名自动接入与白名单/黑名单覆盖
- 缴费 9 列跟踪、付款确认、原群发起人提醒和原行状态更新
- 开庭、缴费及分期还款的多档位提醒
- OCR 图片预处理、PDF 多页识别和 AI 法律字段结构化
- 执行文书、开庭传票、还款协议与回款凭证的独立人工工作区
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

`DB_AUTO_CREATE` 默认关闭。旧版本曾开启自动建表、导致 Alembic revision 落后于实际表结构的 SQLite 数据库，也必须先创建一致性备份，再直接执行 `alembic upgrade head`；迁移会保留已存在的业务表和记录，只补齐缺失结构与数据回填。

## 备份与发布

`deploy/legal-wecom-backup.timer` 每天运行一致性备份，默认保留 14 天。备份包含 SQLite 在线快照、媒体压缩包、SHA-256 清单和完整性检查。恢复必须使用独立目录先演练。当前不做异地备份，服务器整机损坏时无法依赖本机备份恢复。

维护窗口执行顺序和 AI 原文上下文风险说明见 [docs/operations-refactor.md](docs/operations-refactor.md)。
