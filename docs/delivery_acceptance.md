# 法务群自动化可交付版本验收说明

本文用于第一版本机 / 内网验收。默认外部依赖均为 mock：企业微信归档、OCR、金山文档同步都不需要真实凭证即可验证完整业务闭环。

## 1. 本机启动

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.cli check-config
uvicorn app.main:app --reload
```

打开管理端：

```text
http://127.0.0.1:8000/admin/
```

默认 `AUTH_ENABLED=false` 时不需要 API Key。若开启鉴权，需要在管理端右上角填写 `X-API-Key`。

## 2. Mock 演示验收

在管理端进入“消息”页，点击“一键生成演示数据”。系统会自动生成：

- 示例案件 `(2026)黔0281民初3118号`
- 判决书、开庭传票、缴费通知、付款截图四条归档文件消息
- 本地 OCR 文本
- 事件、媒体文件、缴费跟踪提醒
- `sync_target=kdocs` 的金山文档 mock 同步日志

也可以直接调用：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/replay-demo
```

验收通过标准：

- “案件”页能看到示例案件。
- “事件”页能看到 `judgment`、`court_notice`、`payment_notice`、`payment_screenshot`。
- “媒体”页对应文件 OCR 状态为 `processed`。
- “提醒”页生成 7 条 `payment_tracking`。
- “同步日志”页出现 `legal_document_upload`、`enforcement_progress`、`court_time`、`payment_registration`，目标为 `kdocs`。

## 3. 自定义样例验收

用真实样例的 OCR 文本验证抽取效果：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/replay-with-ocr \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"seq":10,"msgid":"msg_real_sample","roomid":"group_001","from":"user_001","msgtype":"file","file":{"filename":"判决书.pdf","md5sum":"dev","filesize":100},"msgtime":1780300000000}],"ocr_text_by_msgid":{"msg_real_sample":"民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三"}}'
```

重点检查字段：

- 案号
- 原告
- 被告
- 文书类型：判决书 / 调解书 / 裁定书 / 开庭传票
- 开庭时间
- 金额
- `requires_review`

字段缺失或低置信度时，当前版本会继续入库并通过 `requires_review=true` 标记人工复核需求。

也可以直接运行内置样例包，覆盖判决书、调解书、裁定书、开庭传票、缴费通知，并校验金山 mock 同步日志：

```bash
python3 scripts/acceptance_ocr_samples.py
```

## 4. Mock 到 Real 切换

### 金山文档

mock：

```env
KDOCS_MODE=mock
```

真实写入：

```env
KDOCS_MODE=real
KDOCS_BASE_URL=https://your-kdocs-gateway.example.com
KDOCS_ACCESS_TOKEN=***
KDOCS_SPACE_ID=***
```

当前服务会向 `{KDOCS_BASE_URL}/kdocs/{operation}` 发起请求，建议先通过封装网关对接金山文档官方 API。网关协议见 `docs/kdocs_gateway_contract.md`。

### 企业微信会话存档

mock：

```env
WECOM_ARCHIVE_MODE=mock
MEDIA_DOWNLOAD_MODE=mock
```

真实读取：

```env
WECOM_ARCHIVE_MODE=real
MEDIA_DOWNLOAD_MODE=real
WECOM_CORP_ID=wwee945c1253a61052
WECOM_ARCHIVE_SECRET=***
WECOM_ARCHIVE_PRIVATE_KEY_PATH=./private_key.pem
WECOM_ARCHIVE_PUBLIC_KEY_VER=***
WECOM_ARCHIVE_SIDECAR_URL=http://127.0.0.1:9001/wecom-archive
WECOM_ARCHIVE_SIDECAR_BACKEND=wecom_archive_sidecar.sdk_backend:create_backend
WECOM_FINANCE_SDK_LIBRARY=./wecom_archive_sidecar/sdk/libWeWorkFinanceSdk_C.so
```

在 Linux x86 / OpenSSL 3 服务器安装企业微信官方 SDK v3.0：

```bash
scripts/install_wecom_sdk.sh
```

真实模式必须持续拉取；企业微信官方接口只允许获取最近 5 天内的会话记录。

真实群聊必须经过管理后台“归档群”白名单确认：首次消息只发现 `roomid`，不保存正文。可发送 `#群名识别群 群名称` 自动更新对应记录的显示名称，该特殊消息也不得进入业务库或改变启用状态。将群状态改为“已启用”后重新发送测试材料，才会进入 OCR 和业务同步。未启用群及单聊消息必须显示为 `skipped`，且不得生成消息、媒体或事件记录。

等待真实 Secret/SDK 期间，可使用 sidecar mock 验收 M4 拉取链路：

```bash
WECOM_ARCHIVE_SIDECAR_BACKEND=mock \
WECOM_ARCHIVE_SIDECAR_MOCK_SCENARIO=legal_demo \
uvicorn wecom_archive_sidecar.main:app --host 127.0.0.1 --port 9001
```

主应用临时配置：

```env
WECOM_ARCHIVE_MODE=real
MEDIA_DOWNLOAD_MODE=real
WECOM_ARCHIVE_SIDECAR_MOCK=true
WECOM_ARCHIVE_SIDECAR_URL=http://127.0.0.1:9001/wecom-archive
```

验收脚本：

```bash
python3 scripts/acceptance_wecom_sidecar_mock.py
```

检查当前企业微信配置：

```bash
curl http://127.0.0.1:8000/api/v1/legal/wecom-poc/archive-check/current
```

## 5. 交付前检查

```bash
pytest
python3 -m app.cli check-config
curl http://127.0.0.1:8000/api/v1/health/detail
```

推荐统一执行：

```bash
scripts/release_check.sh
```

对已启动服务执行在线验收：

```bash
LIVE_BASE_URL=http://127.0.0.1:8000 RUN_TESTS=false RUN_ALEMBIC=false scripts/release_check.sh
```

交付前必须确认：

- `.env`、`*.pem`、数据库、媒体文件、缓存文件未提交。
- `KDOCS_ACCESS_TOKEN`、`WECOM_ARCHIVE_SECRET`、私钥不出现在日志、同步日志响应或 git diff 中。
- `/api/v1/health/detail` 不返回 error。
- Mock 演示回放成功。

## 6. 回滚方式

- 保守回滚：将 `.env` 中 `KDOCS_MODE`、`WECOM_ARCHIVE_MODE`、`MEDIA_DOWNLOAD_MODE` 改回 `mock`，重启服务。
- 数据回滚：本地 SQLite 开发环境可备份并替换数据库文件；生产环境应通过数据库备份恢复。
- 同步失败恢复：在“同步日志”页查看 failed 记录，修复配置后调用重试接口。

## 7. 当前非阻塞项

- 企业微信官方 SDK backend 已内置；真实环境仍需填写 Secret、公钥版本号、私钥并完成服务器联调。
- 金山真实 API 网关尚未配置，不影响 mock 同步日志验收。
- OCR 结构化当前以规则为主，后续可接 LLM 提升复杂文书准确率。
