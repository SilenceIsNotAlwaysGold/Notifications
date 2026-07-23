# 法务自动化运维基线

平台 SQLite 数据库是唯一业务事实来源，金山文档仅是可重建、可读回对账的外部视图。历史未归属资料必须在隔离队列人工确认，禁止按群无范围回填。

AI 结构化会发送 OCR 原文及相关窗口内的群聊上下文。业务已接受该供应商传输风险；必须启用 API Key、RBAC 和调用审计，并限制后台访问。审计只保存请求哈希、上下文消息 ID、模型、耗时和 token 用量，不重复保存完整提示词。

生产发送只使用 wecomapi。回调使用不可猜测的路径密钥，校验 GUID、JSON、请求大小和速率。Android、CLI、机器人、Webhook 和自建协议账号不属于生产架构。

每天执行本机一致性备份，保留 14 天。备份包含 SQLite 在线快照、媒体压缩包、SHA-256 清单和完整性检查。当前不做异地备份，已接受“服务器整机损坏时本机备份也无法恢复”的风险。

维护窗口顺序：停止入口写入，执行完整备份，对生产数据库副本运行 `scripts/migration_preflight.py` 和 Alembic 升级，确认后停止服务、正式升级、记录 Git commit 和 migration revision，再启动并检查健康接口。历史重放必须分批执行，每批完成金山读回对账后才能继续。

源码发布使用删除式同步时，必须保留 `.env`、`.venv`、`data/`、`storage/`、`backups/`、`wecom_archive_seq.txt` 和 `wecom_archive_sidecar/sdk/`。SDK 动态库不进入 Git；缺失时只能执行 `scripts/install_wecom_sdk.sh wecom_archive_sidecar/sdk`，并依赖脚本内固定的 SHA-256 与 MD5 校验恢复。

法律资料默认永久保留，`LEGAL_DATA_RETENTION_ENABLED=false`。只有管理员明确设置为 `true` 后，每日任务才会按 `LEGAL_DATA_RETENTION_DAYS` 和 `LEGAL_DATA_RETENTION_REVIEW_STATUSES` 删除本地文件字节；数据库记录、哈希和审计不会删除。启用前必须确认备份、合规期限和允许清理的复核状态。

商家问题超时只在 `MERCHANT_WORKDAYS` 与 `MERCHANT_WORKDAY_START/END` 定义的工作时间内计时。群的第一个告警人员是负责人；超过 `MERCHANT_QUESTION_ESCALATION_MINUTES` 仍未回复时，升级给第二个告警人员（未配置第二人时仍通知负责人）。
