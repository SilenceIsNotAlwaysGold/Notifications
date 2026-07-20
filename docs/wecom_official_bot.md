# 官方企业微信智能机器人发送

## 1. 适用场景

当 `wecom-cli msg --help` 返回“当前企业暂不支持授权机器人消息使用权限”时，可使用企业微信官方智能机器人的 WebSocket 长连接发送提醒。该路线不要求手机或企业微信客户端常驻。

本项目的 `wecom_bot_sidecar` 使用官方 `@wecom/aibot-node-sdk`，连接 `wss://openws.work.weixin.qq.com`，主服务通过本机 HTTP 调用 sidecar。机器人凭据只在 sidecar 进程内解密，不会返回给主服务、管理端或日志。

## 2. 初始化与验证

服务器需要 Node.js 18 或更高版本。先用官方 CLI 扫码创建机器人并生成加密凭据：

```bash
export WECOM_CLI_CONFIG_DIR=/opt/legal-wecom-automation/secrets/wecom-cli
wecom-cli init
```

配置目录中应存在：

- `.encryption_key`
- `bot.enc`
- `mcp_config.enc`

将目录权限限制为服务账号可读，并确保它不进入 Git、Web 静态目录或公开备份。

安装依赖并执行只连接、不发消息的探针：

```bash
cd /opt/legal-wecom-bot-sidecar
npm ci --omit=dev
WECOM_BOT_CONFIG_DIR=/opt/legal-wecom-automation/secrets/wecom-cli npm run probe
```

输出 `authenticated` 才表示 WebSocket 凭据可用。

## 3. Sidecar 配置

创建仅 root 可读的 `/etc/legal-wecom-bot-sidecar.env`：

```env
WECOM_BOT_CONFIG_DIR=/opt/legal-wecom-automation/secrets/wecom-cli
WECOM_BOT_SIDECAR_TOKEN=至少32位随机字符串
WECOM_BOT_LISTEN_HOST=127.0.0.1
WECOM_BOT_LISTEN_PORT=8788
WECOM_BOT_ALLOWED_ROOM_IDS=wrxxxxxxxx,wcxxxxxxxx
WECOM_BOT_MAX_TEXT_BYTES=2048
```

`WECOM_BOT_ALLOWED_ROOM_IDS` 必须填写会话内容存档发现的官方群 ID。空白名单允许启动和健康检查，但拒绝所有发送。

安装项目提供的 [systemd 模板](../deploy/legal-wecom-bot-sidecar.service) 后启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now legal-wecom-bot-sidecar
curl http://127.0.0.1:8788/health
```

健康响应中的 `ready=true` 表示机器人在线。响应不会包含 Bot ID、Secret 或 sidecar token。

## 4. 主服务配置

sidecar 健康后再修改主服务环境变量：

```env
WECOM_SEND_MODE=wecom_bot
WECOM_BOT_SIDECAR_URL=http://127.0.0.1:8788
WECOM_BOT_SIDECAR_TOKEN=与sidecar相同的随机字符串
WECOM_BOT_TIMEOUT_SECONDS=10
WECOM_BOT_MIN_INTERVAL_SECONDS=1
WECOM_BOT_DAILY_LIMIT=200
WECOM_BOT_GROUP_DAILY_LIMIT=10
WECOM_BOT_FAILURE_THRESHOLD=3
WECOM_BOT_COOLDOWN_SECONDS=300
```

运行 `python -m app.cli check-config`，确认 `WECOM_SEND_MODE` 为 `ok`。主服务还会检查目标群是否已在管理后台“归档群”中启用；sidecar 会再次检查群 ID 白名单。

## 5. 启用顺序

1. sidecar 使用空白名单启动，确认 `ready=true`。
2. 从管理后台确认目标群名称和官方 `room_id`。
3. 把一个测试群加入 sidecar 白名单并重启 sidecar。
4. 保持主服务 `WECOM_SEND_MODE=mock`，手工调用 sidecar 发送无敏感内容的测试消息。
5. 确认目标群收到消息后，才把主服务切换为 `wecom_bot`。

任何一步失败都保持 `mock`，不会自动回退到非官方发送通道。
