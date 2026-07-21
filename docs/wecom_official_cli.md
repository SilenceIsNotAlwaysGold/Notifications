# 官方企业微信 CLI 发送方案

## 1. 定位

首选使用企业微信团队维护的 `WecomTeam/wecom-cli` 发送外部群文字提醒。它通过官方 MCP 配置工作，可在 Linux 服务器常驻运行，不要求手机或企业微信客户端常驻。

本项目仅调用 `msg send_message`，不会让 CLI 读取或上传判决书、身份证明、付款截图等敏感文件。读取材料仍由企业微信会话内容存档 SDK 完成。

## 2. 开放范围

官方当前说明：

- 10 人及以下企业可使用消息、文档、日程、会议、待办等 CLI 能力。
- 10 人以上企业默认提供文档和待办 CLI 能力。

所以扫码成功只表示凭证配置完成，不表示消息能力已经开放。必须执行 `wecom-cli msg --help` 并完成测试群实发。

源码审计结果表明，CLI 会向企业微信官方
`/cgi-bin/aibot/cli/get_mcp_config` 端点获取能力列表，然后按 `biz_type`
查找 `msg` 类别。列表中没有 `msg` 时，拒绝由 CLI 在本地生成，但决策数据
来自企业微信服务端。因此更换 Linux 服务器、重新扫码或修改开源 CLI
都不会产生未授权的消息能力。参见
[WecomTeam/wecom-cli](https://github.com/WecomTeam/wecom-cli)。

## 3. 安装和初始化

服务器需要 Node.js 18 或更高版本：

```bash
npm install -g @wecom/cli
export WECOM_CLI_CONFIG_DIR=/opt/legal-wecom/secrets/wecom-cli
wecom-cli init
wecom-cli msg --help
```

`init` 会展示企业微信扫码流程，只需初始化一次。完成后配置目录中应存在加密的 `bot.enc` 和 `mcp_config.enc`。目录权限应限制为服务账号可读写，并从 Git、备份公开目录和 Web 静态目录排除。

测试群实发：

```bash
wecom-cli msg send_message '{"chat_type":2,"chatid":"wrxxxxxxxx","msgtype":"text","text":{"content":"致和法务测试提醒"}}'
```

只有返回 `errcode=0` 才表示发送成功。

## 4. 主服务配置

```env
WECOM_SEND_MODE=wecom_cli
WECOM_CLI_BINARY=wecom-cli
WECOM_CLI_CONFIG_DIR=/opt/legal-wecom/secrets/wecom-cli
WECOM_CLI_TIMEOUT_SECONDS=35
WECOM_CLI_MIN_INTERVAL_SECONDS=1
WECOM_CLI_DAILY_LIMIT=200
WECOM_CLI_GROUP_DAILY_LIMIT=10
WECOM_CLI_FAILURE_THRESHOLD=3
WECOM_CLI_COOLDOWN_SECONDS=300
```

运行配置预检：

```bash
python -m app.cli check-config
```

预检会检查 CLI 可执行文件和两个加密配置文件，但无法代替企业微信侧权限探测。

## 5. 群白名单

发送时使用会话内容存档中的官方 `roomid`：

- `wr...`：外部客户群等群聊 ID。
- `wc...`：其他群聊 ID。

系统只允许向管理后台“归档群”中状态为“已启用”的群发送。新发现群默认不发送；管理员用 `#群名识别群 致和法务执行群` 标记名称并人工启用后，提醒链路才可调用 CLI。

## 6. 失败与回退

- CLI 不存在或未初始化：配置预检报错，服务不得切到真实发送。
- 没有 `msg` 能力：内部群可继续验证官方智能机器人 WebSocket sidecar，参见 [官方企业微信智能机器人发送](wecom_official_bot.md)。
- 官方机器人无法加入目标外部群：使用客户群群发任务并让成员确认。
- 必须完全无人值守：最后才使用隔离通知账号和 Android RPA，且只发送必要文字。

无论选择哪条通道，会话读取、OCR、金山文档同步和提醒状态机都不需要修改。
