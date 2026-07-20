# legal-wecom-automation

企业微信法务群自动化系统 MVP。

## 当前阶段能力

- 创建和查询法务案件。
- 模拟企业微信群消息进入系统。
- 使用正则识别案号、金额、缴费通知、付款完成、开庭、判决、逾期/执行关键词。
- 保存群消息、结构化事件、提醒、金山文档同步日志。
- 缴费通知自动生成 7 天每日跟踪提醒。
- 付款完成消息自动累加案件已还金额。
- APScheduler 每分钟扫描待发送提醒，也可以手动调用 run-due 接口。
- 企业微信群机器人发送链路支持 mock / webhook 两种模式。
- 企业微信归档 image/file/pdf 消息可落库为媒体文件，并支持 mock 或 sidecar 下载。
- OCR 支持 mock、本地文本调试，以及腾讯/阿里 sidecar provider。
- 支持案件状态扫描：到期前提醒、逾期标记、违约升级、已还清标记 paid。

## 当前阶段限制

- 企业微信读取必须走官方会话内容存档；系统本体不做非官方 hook、网页版模拟或 cookie 抓取。
- 企业微信会话存档和媒体下载 real 模式依赖 SDK sidecar。
- 腾讯/阿里 OCR real 模式依赖 OCR sidecar。
- 腾讯文档 real 模式依赖客户提供可用的文档 API 网关、token 和表格配置。

## 项目结构

```text
app/
├── main.py
├── core/
│   ├── config.py
│   ├── logging.py
│   └── scheduler.py
├── db/
│   ├── base.py
│   ├── session.py
│   └── types.py
├── models/
├── schemas/
├── api/
│   └── v1/
│       ├── router.py
│       ├── cases.py
│       ├── messages.py
│       ├── reminders.py
│       ├── media_files.py
│       ├── document_sync_logs.py
│       ├── observability.py
│       └── events.py
├── services/
├── adapters/
└── utils/
alembic/
├── env.py
└── versions/
```

## 配置

```bash
cp .env.example .env
```

`.env.example`:

```env
APP_NAME=legal-wecom-automation
APP_ENV=local
DEBUG=true
DATABASE_URL=sqlite:///./legal_wecom.db
DB_AUTO_CREATE=true
TIMEZONE=Asia/Shanghai
AUTH_ENABLED=false
ADMIN_API_KEYS=
PUBLIC_ENDPOINTS=/api/v1/health,/api/v1/health/detail
RBAC_ENABLED=true
DEFAULT_API_KEY_ROLE=admin
RESOURCE_SCOPE_ENABLED=true
TENANT_ENABLED=true
TENANT_SETTINGS_ENABLED=true
SECRET_VALUE_MASK=******
TENANT_SECRET_ENCRYPTION_KEY=
WECOM_SEND_MODE=mock
WECOM_WEBHOOK_URL=
WECOM_TIMEOUT_SECONDS=8
WECOM_MAX_RETRY=3
WECOM_ARCHIVE_MODE=mock
WECOM_CORP_ID=
WECOM_ARCHIVE_SECRET=
WECOM_ARCHIVE_PRIVATE_KEY_PATH=
WECOM_ARCHIVE_PUBLIC_KEY_VER=
WECOM_ARCHIVE_SIDECAR_URL=
WECOM_ARCHIVE_SEQ_FILE=./wecom_archive_seq.txt
WECOM_ARCHIVE_LIMIT=100
WECOM_ARCHIVE_TIMEOUT_SECONDS=10
WECOM_ARCHIVE_AUTO_PULL=false
MEDIA_STORAGE_DIR=./storage/media
MEDIA_PUBLIC_BASE_URL=
MEDIA_DOWNLOAD_MODE=mock
MEDIA_MAX_FILE_SIZE_MB=50
TENCENT_DOC_MODE=mock
TENCENT_DOC_BASE_URL=
TENCENT_DOC_APP_ID=
TENCENT_DOC_APP_SECRET=
TENCENT_DOC_ACCESS_TOKEN=
TENCENT_DOC_SHEET_ID=
TENCENT_DOC_TIMEOUT_SECONDS=10
TENCENT_DOC_CASE_NO_COLUMN=案号
TENCENT_DOC_STATUS_COLUMN=状态
TENCENT_DOC_PAID_AMOUNT_COLUMN=已还金额
TENCENT_DOC_ARCHIVE_SHEET_NAME=资料台账
TENCENT_DOC_CASE_SHEET_NAME=案件台账
REPAYMENT_REMINDER_DAYS_BEFORE=3
DEFAULT_UPGRADE_DAYS_AFTER_OVERDUE=3
CASE_STATUS_SCAN_ENABLED=true
CASE_STATUS_SCAN_HOUR=1
CASE_STATUS_SCAN_MINUTE=0
OCR_PROVIDER=mock
OCR_SIDECAR_URL=
OCR_ENABLE_REPROCESS=true
OCR_MAX_TEXT_LENGTH=20000
LEGAL_EXTRACTION_MODE=regex
LEGAL_LLM_BASE_URL=
LEGAL_LLM_API_KEY=
LEGAL_LLM_MODEL=
LEGAL_LLM_TIMEOUT_SECONDS=30
LEGAL_LLM_MAX_TEXT_LENGTH=16000
LEGAL_LLM_MIN_CONFIDENCE=0.75
LEGAL_LLM_FALLBACK_TO_REGEX=true
```

## 运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

启动后访问管理后台：

```text
http://127.0.0.1:8000/admin
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

## 部署说明

本地开发启动：

```bash
scripts/run_dev.sh
```

Docker 构建并启动：

```bash
docker build -t legal-wecom-automation .
docker run --env-file .env -p 8000:8000 -v "$(pwd)/storage:/app/storage" legal-wecom-automation
```

docker compose 启动：

```bash
docker compose up --build
```

正式环境建议：

- 设置 `APP_ENV=production`。
- 设置 `DB_AUTO_CREATE=false`。
- 部署前执行 `alembic upgrade head`。
- 使用外部持久化卷保存 `storage/` 和数据库文件。
- 企业微信、腾讯文档、OCR 的真实凭证只放在环境变量或部署平台密钥中，不写入代码仓库。

## 健康检查

基础健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

详细健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health/detail
```

详细检查包含：

- `database`：执行 `SELECT 1` 检查数据库连接。
- `config`：运行配置校验，不暴露 secret、token、webhook key。
- `scheduler`：展示 APScheduler 运行状态和已注册任务。
- `storage`：检查 `MEDIA_STORAGE_DIR` 是否存在且可写。
- `auth`：展示鉴权是否开启、管理员 API Key 数量和公开端点列表，不返回 API Key 原文。
- `tenant`：展示多租户隔离是否启用。
- `tenant_settings`：展示租户级配置覆盖是否启用。

整体状态含义：

- `ok`：全部正常。
- `degraded`：存在 warning，但没有 error。
- `error`：存在阻断启动或运行的配置 / 数据库 / 存储错误。

## 配置自检

命令行检查：

```bash
python3 -m app.cli check-config
```

如果存在 error，命令退出码为 `1`；只有 warning 或全部 ok 时退出码为 `0`。

上线前检查：

```bash
scripts/release_check.sh
```

该脚本会执行：

- `pytest -q`
- `alembic upgrade head`
- `python3 -m app.cli check-config`
- 脚本语法和 Python 编译检查
- 敏感 / 运行时文件追踪检查

如果服务已经启动，可追加在线验收：

```bash
LIVE_BASE_URL=http://127.0.0.1:8000 RUN_TESTS=false RUN_ALEMBIC=false scripts/release_check.sh
```

轻量本地预检仍可运行：

```bash
scripts/preflight.sh
```

单独检查迁移：

```bash
scripts/check_migrations.sh
```

## CI

仓库提供 GitHub Actions 配置：

```text
.github/workflows/ci.yml
```

CI 会在 `push` 和 `pull_request` 时执行：

- 安装依赖
- `pytest -q`
- 使用临时 SQLite 执行 `alembic upgrade head`
- `python3 -m compileall app`

## 接口鉴权

本地开发默认关闭鉴权：

```env
AUTH_ENABLED=false
```

生产和客户私有化部署建议开启 API Key 鉴权：

```env
AUTH_ENABLED=true
RBAC_ENABLED=true
RESOURCE_SCOPE_ENABLED=true
ADMIN_API_KEYS=your-long-secret-key
DEFAULT_API_KEY_ROLE=admin
PUBLIC_ENDPOINTS=/api/v1/health,/api/v1/health/detail
```

开启后，所有 `/api/v1/legal/*` 管理接口都需要请求头：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/cases' \
  -H 'X-API-Key: your-long-secret-key' \
  -H 'X-Operator: legal-admin'
```

`GET /api/v1/health` 和 `GET /api/v1/health/detail` 默认公开，不需要 API Key。系统不会在日志或健康检查中返回 API Key 原文。

## RBAC 角色权限

系统内置四种角色：

- `admin`：管理员，拥有 `/api/v1/legal/*` 全部权限。
- `legal`：法务操作员，可查看/创建/编辑案件、创建自定义提醒、查看提醒/事件/媒体/同步日志，并可手动 OCR；不能 replay、重试同步、同步案件快照、查看审计日志或管理 API Key。
- `auditor`：审计只读，可查看案件、提醒、事件、媒体、同步日志、运行日志、状态历史、发送日志和操作审计；不能修改业务数据。
- `system`：系统内部调用，可执行 run-due、scan-status、归档 pull、媒体 OCR、同步重试；不能管理 API Key 或查看操作审计。

`AUTH_ENABLED=false` 时 RBAC 不生效。本地开发仍保持默认关闭鉴权。

## 资源级权限

RBAC 控制“能不能访问某类接口”，资源级权限控制“能访问哪些群 / 案件”。当 `AUTH_ENABLED=true`、`RBAC_ENABLED=true`、`RESOURCE_SCOPE_ENABLED=true` 时，数据库 API Key 可配置：

- `allowed_group_ids`：允许访问的企业微信群 ID。
- `allowed_case_ids`：允许访问的案件 ID。
- `allowed_tenant_ids`：允许访问的租户 / 客户 ID。

空数组表示该维度不限制。`tenant_id`、`group_id`、`case_id` 范围同时存在时必须同时满足。`admin` 默认不受资源范围限制，除非数据库 API Key 显式配置了 `allowed_tenant_ids`。环境变量 `ADMIN_API_KEYS` 兼容旧启动方式，默认不限制资源范围。

创建只能访问 `group_001` 的 legal key：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/api-keys \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "法务A",
    "role": "legal",
    "allowed_group_ids": ["group_001"]
  }'
```

使用该 key 查询案件时，只会看到 `group_001` 范围内的数据；访问其他群或案件会返回 `403`。

## 多租户隔离

`tenant` 表示客户、组织或项目空间。第十四阶段开始，系统支持客户级数据隔离：

- `RBAC_ENABLED` 控制“角色能访问哪些接口”。
- `RESOURCE_SCOPE_ENABLED` 控制“API Key 能访问哪些群 / 案件”。
- `TENANT_ENABLED` 控制“API Key 能访问哪些租户数据”。
- `allowed_tenant_ids` 是租户上层范围，`allowed_group_ids` / `allowed_case_ids` 是下层资源范围。
- `tenant_id` 为空用于兼容旧数据；生产建议新建案件、消息和 API Key 时都明确写入租户。
- `status=disabled` 的租户下，非 admin key 不应继续访问业务数据；admin 仍可查看和处理。

创建租户：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/tenants \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"tenant_001","tenant_name":"三叶草法务","contact_name":"张经理","remark":"企业微信法务群自动化客户"}'
```

创建只能访问 `tenant_001` 的 legal key：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/api-keys \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "三叶草法务A",
    "role": "legal",
    "allowed_tenant_ids": ["tenant_001"]
  }'
```

创建只能访问 `tenant_001` 且限定 `group_001` 的 legal key：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/api-keys \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "三叶草法务A",
    "role": "legal",
    "allowed_tenant_ids": ["tenant_001"],
    "allowed_group_ids": ["group_001"]
  }'
```

使用该 key 查询案件：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/cases?tenant_id=tenant_001' \
  -H 'X-API-Key: lwk_live_xxxxx' \
  -H 'X-Operator: 法务A'
```

创建带租户的案件：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/cases \
  -H 'X-API-Key: lwk_live_xxxxx' \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"tenant_001","case_no":"(2026)黔0281民初3118号","debtor_name":"张三","group_id":"group_001","due_date":"2026-06-30","total_amount":"1000.00"}'
```

## 租户级配置

全局 `.env` 是系统默认配置。`tenant_settings` 可以按租户覆盖企业微信群机器人、腾讯文档、OCR、提醒规则、关键词和功能开关。

规则：

- `TENANT_SETTINGS_ENABLED=true` 时启用租户级配置覆盖。
- 字段为 `null` 或未传表示继承全局配置。
- 敏感字段不会通过 API 明文返回，例如 webhook URL 和腾讯文档 access token。
- 当前阶段使用简单存储和接口脱敏，生产建议配置 `TENANT_SECRET_ENCRYPTION_KEY` 或接入 KMS / 密钥管理。
- `feature_flags.enable_wecom_send=false` 时，租户提醒不会真实发送企业微信。
- `feature_flags.enable_tencent_doc_sync=false` 时，同步日志会记录租户关闭同步。
- `feature_flags.enable_ocr=false` 时，OCR 返回关闭提示。
- `keyword_config` 可覆盖默认关键词词表，例如把“交费”识别为缴费通知。

查看租户配置，返回脱敏结果：

```bash
curl http://127.0.0.1:8000/api/v1/legal/tenants/tenant_001/settings \
  -H 'X-API-Key: admin-key'
```

设置租户 OCR、提醒和关键词：

```bash
curl -X PUT http://127.0.0.1:8000/api/v1/legal/tenants/tenant_001/settings \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "ocr_provider": "local_text",
    "repayment_reminder_days_before": 5,
    "keyword_config": {
      "payment_notice": ["需要缴费", "诉讼费", "交费"],
      "payment_done": ["已付款", "支付成功"]
    }
  }'
```

设置租户企业微信群机器人和腾讯文档配置：

```bash
curl -X PUT http://127.0.0.1:8000/api/v1/legal/tenants/tenant_001/settings \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "wecom_send_mode": "webhook",
    "wecom_webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
    "tencent_doc_mode": "mock",
    "tencent_doc_sheet_id": "sheet_xxx",
    "tencent_doc_case_sheet_name": "租户案件台账",
    "tencent_doc_archive_sheet_name": "租户资料台账",
    "feature_flags": {
      "enable_wecom_send": true,
      "enable_tencent_doc_sync": true,
      "enable_ocr": true,
      "enable_case_lifecycle_scan": true,
      "enable_payment_tracking": true
    }
  }'
```

删除租户配置，恢复继承全局配置：

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/legal/tenants/tenant_001/settings \
  -H 'X-API-Key: admin-key'
```

## API Key 管理

生产建议先用环境变量 `ADMIN_API_KEYS` 启动一个初始 admin key，进入系统后创建数据库 API Key，并逐步轮换掉环境变量 key。数据库中只保存 `key_hash` 和 `key_prefix`，明文 API Key 只在创建时返回一次。

创建 legal key：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/api-keys \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{"name":"法务操作员","role":"legal"}'
```

使用 legal key 查询案件：

```bash
curl http://127.0.0.1:8000/api/v1/legal/cases \
  -H 'X-API-Key: lwk_live_xxxxx' \
  -H 'X-Operator: legal-user'
```

查询 API Key 列表：

```bash
curl http://127.0.0.1:8000/api/v1/legal/api-keys \
  -H 'X-API-Key: admin-key'
```

吊销 API Key：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/api-keys/1/revoke \
  -H 'X-API-Key: admin-key'
```

## 操作审计

`operation_audit_logs` 会记录管理接口调用，用于排查谁在什么时候调用了哪个接口。记录内容包括：

- operator
- auth_type
- operator_role
- api_key_id / api_key_prefix
- method / path / action
- status_code
- client_host
- user_agent
- request / response 摘要

审计日志不会记录 API Key、token、secret、webhook、password、private_key 等敏感字段原文。

查询审计日志：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/operation-audit-logs' \
  -H 'X-API-Key: your-long-secret-key'
```

## 数据库迁移

第九阶段开始引入 Alembic 正式管理数据库结构。推荐正式环境关闭自动建表，先执行迁移：

```env
DB_AUTO_CREATE=false
```

初始化或升级数据库：

```bash
alembic upgrade head
```

生成新迁移：

```bash
alembic revision --autogenerate -m "message"
```

应用迁移：

```bash
alembic upgrade head
```

回滚一个版本：

```bash
alembic downgrade -1
```

查看当前版本：

```bash
alembic current
```

查看迁移历史：

```bash
alembic history
```

本地快速体验仍可使用 `DB_AUTO_CREATE=true`，应用启动时会执行 `create_all`。已有的 SQLite 兼容补列逻辑会继续作为老版本本地库的兜底，但新环境和正式部署建议以 Alembic 为准。

## 企业微信发送通道

默认 mock 模式，不会请求企业微信，只会记录发送结果日志：

```env
WECOM_SEND_MODE=mock
WECOM_WEBHOOK_URL=
```

对于官方 CLI 已向企业开放“消息”能力的场景，优先使用官方 `wecom-cli`。它直接使用会话内容存档发现的 `wr...` / `wc...` 群 ID，不需要维护另一套发送群映射：

```bash
npm install -g @wecom/cli
WECOM_CLI_CONFIG_DIR=~/.config/wecom wecom-cli init
wecom-cli msg --help
```

```env
WECOM_SEND_MODE=wecom_cli
WECOM_CLI_BINARY=wecom-cli
WECOM_CLI_CONFIG_DIR=~/.config/wecom
WECOM_CLI_MIN_INTERVAL_SECONDS=1
WECOM_CLI_DAILY_LIMIT=200
WECOM_CLI_GROUP_DAILY_LIMIT=10
```

当前官方说明中，10 人及以下企业可获得消息等完整 CLI 能力；10 人以上企业默认只列出文档和待办能力。因此 `wecom-cli msg --help` 和测试群实发是启用条件，不能只凭扫码初始化成功判断可用。系统还会要求目标群已在管理端“归档群”中启用，并对文本执行 2048 字节限制、单群/全局每日上限和失败熔断。详细操作见 [官方企业微信 CLI 发送方案](docs/wecom_official_cli.md)。

如果 CLI 消息品类未授权，可使用已集成的官方智能机器人 WebSocket sidecar。它复用扫码生成的加密机器人凭据，不要求手机常驻：

```env
WECOM_SEND_MODE=wecom_bot
WECOM_BOT_SIDECAR_URL=http://127.0.0.1:8788
WECOM_BOT_SIDECAR_TOKEN=与sidecar一致的随机字符串
WECOM_BOT_MIN_INTERVAL_SECONDS=1
WECOM_BOT_DAILY_LIMIT=200
WECOM_BOT_GROUP_DAILY_LIMIT=10
```

sidecar 必须只监听本机，并单独配置 `WECOM_BOT_ALLOWED_ROOM_IDS`。目标群还必须在管理端“归档群”中启用，两道白名单同时通过才会发送。部署和渐进启用步骤见 [官方企业微信智能机器人发送](docs/wecom_official_bot.md)。

启用真实群机器人 webhook 发送：

```env
WECOM_SEND_MODE=webhook
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的机器人key
WECOM_TIMEOUT_SECONDS=8
WECOM_MAX_RETRY=3
```

当官方 CLI 未开放消息能力，且官方智能机器人也无法加入目标外部群时，项目另提供可选的 `wecomapi` 兼容发送模式，用于专用通知账号向已映射的外部群发送文本。该模式可以连接第三方网关，也可以连接项目内置的自托管 Android RPA 网关：

```env
WECOM_SEND_MODE=wecomapi
WECOMAPI_BASE_URL=http://127.0.0.1:8092
WECOMAPI_API_PATH=/wecom/finder/api
WECOMAPI_TOKEN=自托管网关Token
WECOMAPI_GUID=自托管网关robot_id
WECOMAPI_MIN_INTERVAL_SECONDS=3
WECOMAPI_DAILY_LIMIT=200
WECOMAPI_FAILURE_THRESHOLD=3
WECOMAPI_COOLDOWN_SECONDS=300
```

启用前必须在管理端“归档群”页面，为每个官方归档 `roomid` 单独填写发送目标白名单 ID。缺少映射、群未启用或网关配置缺失时，系统会阻止发送。该模式按专用账号串行限速，并带进程内每日上限和连续失败熔断。

自托管网关启动命令：

```bash
uvicorn wecom_sender_sidecar.main:app --host 127.0.0.1 --port 8092
```

该通道通过非官方 UI 自动化完成外部群发送。生产环境应使用独立的“致和法务通知助手”账号，只发送必要的文字提醒，不通过该通道传输判决书、身份证明等敏感文件。详细操作见 [企业微信外部群自托管发送方案](docs/wecom_self_hosted_sender.md) 和 [企业微信专用通知账号接入](docs/wecom_dedicated_sender.md)。

## 企业微信真实接入风险

真实接入企业微信外部法务群前，必须先完成可行性验证：

- 企业微信群机器人 webhook 只负责发送消息，不能读取群消息。
- 外部群是否支持添加机器人必须在客户目标群中实际验证。
- 如果外部群不能添加机器人，则 webhook 方案不能用于该群提醒。
- 读取群消息必须优先走企业微信官方会话内容存档。
- 没有会话内容存档权限，就无法通过官方方式读取企业微信群消息。
- 会话内容存档还需要确认是否覆盖外部群、群内员工和图片/PDF/文件等媒体。
- 非官方 UI 自动化通道仅作为可选外发能力，默认关闭，不承担会话读取和文件传输。
- 当前系统支持 replay 模拟消息进入业务链路，但 replay 成功不代表已经真实接入企业微信生产环境。

企业微信 POC 文档：

- [企业微信接入可行性说明](docs/wecom_integration_feasibility.md)
- [企业微信接入客户确认清单](docs/wecom_customer_checklist.md)

现场测试 webhook 发送：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-poc/send-test \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{"webhook_url":"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx","content":"企业微信机器人发送测试"}'
```

检查会话内容存档配置完整性：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-poc/archive-check \
  -H 'X-API-Key: admin-key' \
  -H 'Content-Type: application/json' \
  -d '{"corp_id":"wwxxxx","archive_secret":"xxx","private_key_path":"/secure/private.pem","public_key_ver":"1","sidecar_url":"http://127.0.0.1:9001/wecom-archive"}'
```

也可以直接检查当前环境变量配置：

```bash
curl http://127.0.0.1:8000/api/v1/legal/wecom-poc/archive-check/current \
  -H 'X-API-Key: admin-key'
```

## 企业微信会话内容存档

当前系统提供会话内容存档 replay 调试流程，并支持在 `WECOM_ARCHIVE_MODE=real` 时通过 SDK sidecar 拉取已解密消息。系统本体不使用个人号 hook、不模拟网页版、不抓取 cookie；真实企业微信会话存档需要由 sidecar 封装企业微信官方会话内容存档 SDK。

真实接入需要客户开通企业微信会话内容存档，并提供：

- 企业 ID `corp_id`
- 会话内容存档 `secret`
- private key
- public key version
- 已开通的员工 / 群范围
- SDK sidecar 地址 `WECOM_ARCHIVE_SIDECAR_URL`

sidecar 约定：

- 系统会向 `{WECOM_ARCHIVE_SIDECAR_URL}/messages` 发起 `POST` 请求。
- 请求体包含 `seq`、`limit`、`corp_id`、`archive_secret`、`private_key_path`、`public_key_ver`。
- 响应体应为 `{"messages":[...]}`，其中每条消息使用企业微信归档原始字段，如 `seq`、`msgid`、`roomid`、`from`、`msgtype`、`text`、`image`、`file`、`msgtime`。

仓库内提供了一个最小 sidecar 外壳，路径为 `wecom_archive_sidecar/main.py`。本地联调可先启动 mock backend：

```bash
WECOM_ARCHIVE_SIDECAR_BACKEND=mock \
WECOM_ARCHIVE_SIDECAR_MOCK_SCENARIO=legal_demo \
uvicorn wecom_archive_sidecar.main:app --host 127.0.0.1 --port 9001
```

然后主应用配置：

```env
WECOM_ARCHIVE_MODE=real
MEDIA_DOWNLOAD_MODE=real
WECOM_ARCHIVE_SIDECAR_MOCK=true
WECOM_ARCHIVE_SIDECAR_URL=http://127.0.0.1:9001/wecom-archive
```

`WECOM_ARCHIVE_SIDECAR_MOCK=true` 只用于本地验收：它允许暂时缺少 `WECOM_ARCHIVE_SECRET`、`WECOM_ARCHIVE_PRIVATE_KEY_PATH`、`WECOM_ARCHIVE_PUBLIC_KEY_VER`。生产或真实 SDK 联调时应关闭该开关并填写真实凭证。

启动主应用后，可运行 M4 mock 验收脚本：

```bash
python3 scripts/acceptance_wecom_sidecar_mock.py
```

仓库已内置企业微信官方 Linux x86 SDK v3.0 backend。Ubuntu 24.04 / OpenSSL 3 环境可直接安装官方 SDK：

```bash
scripts/install_wecom_sdk.sh
```

脚本仅从企业微信官方 CDN 下载固定版本，并校验压缩包 SHA256 和动态库 MD5。SDK 二进制不会进入 Git。sidecar 真实模式配置：

```env
WECOM_ARCHIVE_SIDECAR_BACKEND=wecom_archive_sidecar.sdk_backend:create_backend
WECOM_FINANCE_SDK_LIBRARY=./wecom_archive_sidecar/sdk/libWeWorkFinanceSdk_C.so
WECOM_FINANCE_SDK_TIMEOUT_SECONDS=10
WECOM_ARCHIVE_MEDIA_MAX_BYTES=52428800
```

启动 sidecar：

```bash
uvicorn wecom_archive_sidecar.main:app --host 127.0.0.1 --port 9001
```

backend 按官方流程执行 `GetChatData`、RSA/PKCS1 随机密钥解密、`DecryptData` 和 `GetMediaData` 分片下载。消息只能获取最近 5 天内尚未过期的数据，生产环境必须持续拉取并持久化 `seq`。官方接口说明：[获取会话内容](https://developer.work.weixin.qq.com/document/path/91774)。

### 法务群白名单

企业微信后台配置的是“哪些员工允许存档”，本系统另外维护“哪些群允许进入法务业务”的 `roomid` 白名单。真实拉取遵循以下规则：

- 新 `roomid` 首次出现时仅登记为 `discovered`，只保存群 ID、首次/最后发现时间和消息数量，不保存消息正文或媒体。
- 可在管理后台生成 `#群名识别群 群名称` 特殊消息并发送到目标群；系统会自动更新对应 `roomid` 的显示名称，特殊消息本身不会进入业务库，也不会改变群的启用状态。
- 只有管理后台“归档群”页面中状态为 `enabled` 的群，才会保存消息并进入 OCR、提醒和金山文档同步。
- `disabled` 群和没有 `roomid` 的单聊消息直接跳过，但仍推进归档 `seq`，避免重复拉取。
- 首条用于发现群聊的消息不会补处理；管理员启用群后，应重新发送测试材料。
- 管理员也可在“归档群”列表修改显示名称、所属客户和状态。
- replay 和演示接口不执行白名单过滤，便于独立验收 mock 业务链路。

管理 API：

```bash
curl http://127.0.0.1:8000/api/v1/legal/wecom-archive/groups \
  -H 'X-API-Key: admin-key'

curl -X PATCH http://127.0.0.1:8000/api/v1/legal/wecom-archive/groups/wrxxxxxxxx \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: admin-key' \
  -d '{"display_name":"法务执行群","status":"enabled"}'
```

本地可以通过 replay 接口模拟真实归档消息进入系统：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/replay \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"seq":1,"msgid":"msg_001","roomid":"group_001","from":"user_001","msgtype":"text","text":{"content":"案件(2026)黔0281民初3118号需要缴费400元，7天内完成"},"msgtime":1780300000000}]}'
```

开发阶段也可以一次性回放归档文件并注入 OCR 文本，适合在企业微信和真实 OCR 都未接入时验收金山文档 mock 闭环：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/replay-with-ocr \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"seq":10,"msgid":"msg_dev_judgment","roomid":"group_001","from":"user_001","msgtype":"file","file":{"filename":"判决书.pdf","md5sum":"dev","filesize":100},"msgtime":1780300000000}],"ocr_text_by_msgid":{"msg_dev_judgment":"民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三"}}'
```

这个接口会自动生成本地同名 `.txt` OCR 文本并重跑 OCR，最终产生 `legal_document_upload`、`enforcement_progress` 等 `sync_target=kdocs` 的同步日志。

也可以使用内置演示场景一次性生成示例案件、判决书、开庭传票、缴费通知和付款截图：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/replay-demo
```

M2 样例验收可以直接跑内置 OCR 样例包，脚本会回放判决书、调解书、裁定书、开庭传票、缴费通知，并校验金山 mock 同步日志：

```bash
python3 scripts/acceptance_ocr_samples.py
```

手动触发归档拉取：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/pull
```

默认 `WECOM_ARCHIVE_MODE=mock`，pull 返回空列表。若设置 `WECOM_ARCHIVE_MODE=real`，必须同时配置 `WECOM_ARCHIVE_SIDECAR_URL` 和企业微信归档凭证。若设置 `WECOM_ARCHIVE_AUTO_PULL=true`，APScheduler 会每分钟尝试执行一次归档 pull；本地默认关闭。

## 媒体文件处理

当前支持企业微信归档 `image`、`file`、`pdf` 消息落库到 `legal_media_files`。默认 `MEDIA_DOWNLOAD_MODE=mock`，会在 `MEDIA_STORAGE_DIR` 下写入本地测试文件；若设置 `MEDIA_DOWNLOAD_MODE=real`，系统会通过 SDK sidecar 下载真实媒体文件并保存到 `MEDIA_STORAGE_DIR`。

媒体下载 sidecar 约定：

- 系统会向 `{WECOM_ARCHIVE_SIDECAR_URL}/media/download` 发起 `POST` 请求。
- 请求体包含 `raw_message`、`target_filename`、`corp_id`、`archive_secret`、`private_key_path`、`public_key_ver`。
- 响应体应为 `{"content_base64":"..."}`。
- 系统会校验 `MEDIA_MAX_FILE_SIZE_MB` 后写入本地文件；真实 OCR provider 可直接基于 `local_path` 处理文件。

replay 图片消息：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/replay \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"seq":2,"msgid":"msg_img_001","roomid":"group_001","from":"user_001","msgtype":"image","image":{"md5sum":"abc","filesize":12345},"msgtime":1780300000000}]}'
```

replay PDF 文件消息：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/replay \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"seq":3,"msgid":"msg_file_001","roomid":"group_001","from":"user_001","msgtype":"file","file":{"filename":"判决书.pdf","md5sum":"def","filesize":45678},"msgtime":1780300000000}]}'
```

查询媒体文件：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/media-files?group_id=group_001'
```

手动触发媒体下载 / OCR：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/media-files/1/download
curl -X POST http://127.0.0.1:8000/api/v1/legal/media-files/1/ocr
```

## OCR 本地调试模式

设置：

```env
OCR_PROVIDER=local_text
OCR_ENABLE_REPROCESS=true
OCR_MAX_TEXT_LENGTH=20000
```

`local_text` provider 会读取媒体文件旁边同名 `.txt`，把它当作 OCR 结果。例如已有 PDF：

```text
storage/media/2026/06/02/msg_file_001.pdf
```

创建同名文本：

```text
storage/media/2026/06/02/msg_file_001.txt
```

内容示例：

```text
案件(2026)黔0281民初3118号需要缴费400元，7天内完成
```

然后调用：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/media-files/1/ocr
```

系统会读取 `.txt`，进入案号、金额、关键词识别链路；匹配到案件后会生成 `payment_notice` 事件和 7 条缴费跟踪提醒。付款完成类文本会累加 `paid_amount` 并写入腾讯文档 mock 同步日志。

## OCR Sidecar 模式

设置：

```env
OCR_PROVIDER=tencent
OCR_SIDECAR_URL=http://127.0.0.1:9002
OCR_MAX_TEXT_LENGTH=20000
```

`OCR_PROVIDER` 也可以设置为 `aliyun`。系统会向 `{OCR_SIDECAR_URL}/ocr/extract` 发起 `POST` 请求，请求体包含：

- `provider`：`tencent` 或 `aliyun`
- `media_type`：`image`、`pdf` 或 `file`
- `filename`
- `content_base64`

响应体应为：

```json
{"success": true, "raw_text": "识别出的文本", "confidence": 0.98, "metadata": {}}
```

系统拿到 `raw_text` 后会继续进入统一的案号、金额、关键词解析链路。

仓库内提供了一个轻量腾讯 OCR sidecar，位于 `ocr_sidecar/`。它通过腾讯云
`GeneralBasicOCR` API 识别图片和 PDF，并适配上面的 `/ocr/extract` 协议：

```bash
TENCENT_OCR_SECRET_ID=xxx \
TENCENT_OCR_SECRET_KEY=xxx \
TENCENT_OCR_REGION=ap-guangzhou \
uvicorn ocr_sidecar.main:app --host 127.0.0.1 --port 9002
```

## OCR 后的 LLM 结构化抽取

腾讯 OCR 负责把图片或 PDF 转成文字；案号、原告、被告、材料类型、金额和开庭时间仍需从文字中结构化提取。默认使用正则，不调用外部模型：

```env
LEGAL_EXTRACTION_MODE=regex
```

生产环境可以接入 OpenAI 兼容的模型网关：

```env
LEGAL_EXTRACTION_MODE=llm
LEGAL_LLM_BASE_URL=https://llm-gateway.example.com/v1
LEGAL_LLM_API_KEY=replace-me
LEGAL_LLM_MODEL=your-model
LEGAL_LLM_MIN_CONFIDENCE=0.75
LEGAL_LLM_FALLBACK_TO_REGEX=true
```

系统只把 OCR 文书文本交给 LLM，不会默认发送普通群聊文本。模型输出会经过材料类型、案号、金额、时间和置信度校验；缺少关键字段、与正则结果冲突或低于置信度阈值时会设置 `requires_review=true`。模型请求失败时默认回退到正则，同时记录 `llm_status=fallback` 和复核原因，OCR 主链路不会因此中断。

生产环境建议把腾讯云密钥写入 systemd 环境文件，不要提交到代码仓库。

## 腾讯文档同步

## 金山文档业务闭环

默认 `KDOCS_MODE=mock`，系统不会请求金山文档，只会把稳定的同步 payload 写入 `document_sync_logs`，`sync_target=kdocs`。当前金山文档是新业务主路径，保留旧腾讯文档适配器用于兼容历史代码。

媒体 OCR 识别后会自动触发以下同步：

- 判决书、调解书、裁定书：按 `原告-被告{文书类型}.扩展名` 重命名并上传到 `KDOCS_JUDGMENT_FOLDER_ID`，同时写入强制执行进度表。
- 开庭传票：抽取开庭时间，写入 `KDOCS_COURT_TIME_SHEET_ID`，payload 中声明按“开庭时间”排序。
- 缴费通知、缴费截图、缴费文件：写入 `KDOCS_PAYMENT_SHEET_ID`，并继续创建 7 天缴费跟踪提醒。

配置示例：

```env
KDOCS_MODE=mock
KDOCS_BASE_URL=
KDOCS_ACCESS_TOKEN=
KDOCS_SPACE_ID=
KDOCS_JUDGMENT_FOLDER_ID=致和法务/判决书文件
KDOCS_COURT_TIME_SHEET_ID=致和法务/开庭时间
KDOCS_ENFORCEMENT_SHEET_ID=致和法务/强制执行进度表格
KDOCS_PAYMENT_SHEET_ID=致和法务/缴费登记
KDOCS_CASE_SHEET_ID=致和法务/案件台账
```

`KDOCS_MODE=real` 时必须配置 `KDOCS_BASE_URL`、`KDOCS_ACCESS_TOKEN`、`KDOCS_SPACE_ID`。当前适配器会向 `{KDOCS_BASE_URL}/kdocs/{operation}` 发起请求，可直接指向金山文档官方 API 封装网关；网关协议见 [docs/kdocs_gateway_contract.md](docs/kdocs_gateway_contract.md)。

## 腾讯文档同步

默认 `TENCENT_DOC_MODE=mock`，系统不会请求腾讯文档，只会把稳定的同步 payload 写入 `document_sync_logs`。当前保留腾讯文档兼容适配器，历史支持三类主要同步：

- `status`：案件状态
- `paid_amount`：已还金额
- `archive`：资料归档

另有 `case_snapshot` 用于手动同步案件快照。

真实同步前需要客户确认：

- 腾讯文档类型：在线表格 / 智能表格
- `sheet_id`
- sheet 名称
- 列名
- 行匹配规则，例如按案号匹配
- API 权限和 token 获取方式

字段映射通过环境变量配置：

```env
TENCENT_DOC_CASE_NO_COLUMN=案号
TENCENT_DOC_STATUS_COLUMN=状态
TENCENT_DOC_PAID_AMOUNT_COLUMN=已还金额
TENCENT_DOC_ARCHIVE_SHEET_NAME=资料台账
TENCENT_DOC_CASE_SHEET_NAME=案件台账
```

查询同步日志：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/document-sync-logs?sync_type=archive&status=success'
```

重试失败同步：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/document-sync-logs/1/retry
```

手动同步案件快照：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/cases/1/sync
```

## 案件状态扫描

系统支持每日自动扫描案件状态，也支持手动触发。默认规则：

- 到期前 `REPAYMENT_REMINDER_DAYS_BEFORE` 天创建还款提醒。
- 逾期未还且状态为 `normal` 时自动标记 `overdue`。
- 逾期满 `DEFAULT_UPGRADE_DAYS_AFTER_OVERDUE` 天自动升级 `defaulted`。
- `paid_amount >= total_amount` 时自动标记 `paid`。
- `closed` 案件不参与扫描。
- 状态变化会写文档同步日志，当前新需求主路径为金山文档。
- 违约升级只提醒法务，不自动执行任何法律动作。

每日扫描通过以下配置控制：

```env
CASE_STATUS_SCAN_ENABLED=true
CASE_STATUS_SCAN_HOUR=1
CASE_STATUS_SCAN_MINUTE=0
```

手动触发扫描：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/cases/scan-status
```

## 运行日志与审计

系统提供三类可观测性日志：

- `system_run_logs`：记录自动任务和手动任务运行情况，例如提醒发送、案件扫描、归档拉取、OCR 处理、同步重试。
- `case_status_histories`：记录案件状态变更历史，包括旧状态、新状态、原因和变更前后快照。
- `reminder_send_logs`：记录每次提醒发送尝试，包括发送模式、请求摘要、响应摘要和失败原因。

查询运行日志：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/system-run-logs'
```

查询案件状态历史：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/cases/1/status-histories'
```

查询提醒发送日志：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/reminders/1/send-logs'
```

## 接口示例

创建案件：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/cases \
  -H 'Content-Type: application/json' \
  -d '{"case_no":"(2026)黔0281民初3118号","debtor_name":"张三","group_id":"group_001","debtor_wecom_userid":"debtor_001","lawyer_wecom_userid":"lawyer_001","due_date":"2026-06-30","total_amount":"1000.00"}'
```

绑定真实归档群和企微成员：

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/legal/cases/1 \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"tenant_001","group_id":"wrxxxxxxxx","debtor_wecom_userid":"debtor_001","lawyer_wecom_userid":"lawyer_001"}'
```

更新绑定后，系统会迁移该案件尚未发送的提醒。目标群只绑定一个案件时，还会把该群内尚未关联的历史媒体和事件回填到案件；一群多案时不会猜测归属，需要依靠案号识别或人工复核。

查询案件：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/cases?group_id=group_001&status=normal'
```

模拟群消息：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/messages/mock \
  -H 'Content-Type: application/json' \
  -d '{"group_id":"group_001","sender_id":"user_001","msg_type":"text","content":"案件(2026)黔0281民初3118号需要缴费400元，7天内完成"}'
```

模拟付款完成消息：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/messages/mock \
  -H 'Content-Type: application/json' \
  -d '{"group_id":"group_001","sender_id":"user_001","msg_type":"text","content":"案件(2026)黔0281民初3118号付款截图，已支付¥400"}'
```

创建自定义提醒：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/reminders/custom \
  -H 'Content-Type: application/json' \
  -d '{"group_id":"group_001","remind_at":"2026-06-02T15:30:00+08:00","content":"请跟进开庭材料","target_userid":"lawyer_001"}'
```

手动触发到期提醒：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/reminders/run-due
```

run-due 会返回发送统计：

```json
{
  "code": 0,
  "message": "到期提醒扫描完成",
  "data": {
    "sent": 1,
    "failed": 0,
    "retrying": 0,
    "total": 1
  }
}
```

查询提醒：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/reminders?status=pending'
```

查询事件：

```bash
curl 'http://127.0.0.1:8000/api/v1/legal/events?event_type=payment_notice'
```

## 运维交付

生产 Compose 包含 API、OCR sidecar、归档 sidecar、迁移任务和备份任务；企业微信机器人通过 `robot` profile 可选启用。只有 API 对宿主机暴露端口。

```bash
docker compose up --build -d
docker compose --profile operations run --rm backup
```

管理端“系统告警”页面覆盖归档停滞、OCR/LLM/金山连续失败、机器人离线、备份过期和磁盘不足。备份校验、恢复、回滚及 systemd timer 安装步骤见 [运维文档](docs/operations.md)。

## 测试

```bash
pytest -q
```
