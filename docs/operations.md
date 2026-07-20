# 运维、告警与备份恢复

## 系统告警

后台“系统告警”页面每 5 分钟检查一次：企业微信归档停滞、OCR/LLM/金山连续失败、机器人离线、备份过期和磁盘空间不足。新告警可选推送到 `OPS_WEBHOOK_URL`，告警确认不会掩盖异常；检测恢复后状态自动变为 `resolved`。

手工扫描：

```bash
curl -X POST -H "X-API-Key: $ADMIN_API_KEY" \
  http://127.0.0.1:8000/api/v1/legal/system-alerts/scan
```

## 一致性备份

备份使用 SQLite Online Backup API，不直接复制正在写入的数据库。每个备份目录包含：

- `legal_wecom.db`：一致性数据库快照，并通过 `PRAGMA integrity_check`。
- `media.tar.gz`：媒体文件压缩包。
- `manifest.json`：文件大小和 SHA-256 校验清单。

本机执行：

```bash
python3 scripts/backup.py \
  --database ./legal_wecom.db \
  --media ./storage/media \
  --output ./storage/backups \
  --retention-days 14
```

Compose 执行：

```bash
docker compose --profile operations run --rm backup
```

## 恢复与回滚

1. 停止 API 和定时任务。
2. 先运行恢复命令；命令会在替换前校验清单、SHA-256 和 SQLite 完整性。
3. 启动 API，检查 `/api/v1/health/detail`、案件数量和最近媒体文件。
4. 恢复命令会保留 `.pre-restore-时间戳` 数据库和媒体目录；验收失败时可停机后换回。

```bash
python3 scripts/restore.py ./storage/backups/20260720T023000Z \
  --database ./legal_wecom.db \
  --media ./storage/media \
  --force
```

使用 Compose 命名卷部署时，在容器内恢复：

```bash
docker compose stop api
docker compose --profile operations run --rm backup \
  python -m app.ops.restore /app/backups/20260720T023000Z --force
docker compose up -d api
```

损坏或缺文件的备份会在替换任何现有数据前被拒绝。

## systemd 定时器

将 `deploy/legal-wecom-backup.service` 与 `deploy/legal-wecom-backup.timer` 安装到 `/etc/systemd/system/`，按实际部署目录调整 `WorkingDirectory`，然后执行：

```bash
systemctl daemon-reload
systemctl enable --now legal-wecom-backup.timer
systemctl list-timers legal-wecom-backup.timer
```

## 可选机器人容器

启用 `robot` profile 前，将专用机器人账号生成的 `bot.enc` 和 `mcp_config.enc` 放入 `WECOM_BOT_CONFIG_HOST_DIR`（默认 `./storage/wecom-bot`）。该目录以只读方式挂载，凭证不会写入镜像或 Git。

```bash
mkdir -p storage/wecom-bot
docker compose --profile robot up -d wecom-bot api
```
