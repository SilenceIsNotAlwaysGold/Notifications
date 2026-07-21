# 企业微信 Linux 自托管账号网关

## 定位

`wecom_protocol_gateway` 是企业微信账号通道的自托管控制面。主业务只调用本地兼容 API，不直接绑定第三方网关或未来的原生客户端协议实现。

第一阶段已经提供：

- `POST /api/qw/doApi` 和兼容路径 `POST /wecom/finder/api`。
- 单账号 `guid` 校验、API Token 鉴权和目标群白名单。
- 文本发送、修改群名和登录状态相关方法的固定白名单。
- Mock 驱动、官方 Linux CLI 驱动和第三方上游迁移驱动。
- 回调快速落库、幂等去重、Fernet 加密、后台转发和失败重试。
- 仅保存账号及目标哈希的操作审计，不保存明文发送内容。

当前没有把第三方未公开的企业微信原生客户端协议伪装成已实现。`upstream` 驱动用于接口对照、小流量验证和收集合法测试账号的行为样本；原生协议驱动必须经过独立测试账号和真实外部群验收后才能标记可用。

## 官方 Linux CLI 驱动

`official_cli` 使用企业微信官方 `WecomTeam/wecom-cli` 的 `msg send_message`
能力。该 CLI 会先请求企业微信服务端的 MCP 能力列表；只有列表中包含
`biz_type=msg` 时才能发送。Linux 和扫码初始化成功都不代表已获得消息权限。

```env
WECOM_PROTOCOL_BACKEND=official_cli
WECOM_PROTOCOL_GUID=zhihe-official-bot
WECOM_PROTOCOL_OFFICIAL_CLI_BINARY=wecom-cli
WECOM_PROTOCOL_OFFICIAL_CLI_CONFIG_DIR=/opt/legal-wecom/secrets/wecom-cli
WECOM_PROTOCOL_OFFICIAL_CLI_TIMEOUT_SECONDS=35
```

使用网关 Token 显式探测权限：

```bash
curl -X POST http://127.0.0.1:8092/api/qw/capabilities/probe \
  -H 'WECOM-TOKEN: 网关Token'
```

`message_capability=granted` 才可启用真实发送；`denied` 表示服务端未向当前企开放
`msg` 能力。这种情况不能通过更换 Linux 发行版、重新扫码或修改 CLI
绕过。该驱动只支持文本发送，不支持修改群名、设备登录或接收群消息。

## Mock 启动

```env
WECOM_PROTOCOL_BACKEND=mock
WECOM_PROTOCOL_API_TOKEN=生成的高强度随机Token
WECOM_PROTOCOL_GUID=device-zhihe-001
WECOM_PROTOCOL_ROOM_IDS_JSON={"zhihe-legal":"wr-external-room-001"}
WECOM_PROTOCOL_STATE_KEY=生成的FernetKey
```

```bash
uvicorn wecom_protocol_gateway.main:app --host 127.0.0.1 --port 8092
```

主服务继续使用原来的适配器：

```env
WECOM_SEND_MODE=wecomapi
WECOMAPI_BASE_URL=http://127.0.0.1:8092
WECOMAPI_API_PATH=/api/qw/doApi
WECOMAPI_TOKEN=与WECOM_PROTOCOL_API_TOKEN相同
WECOMAPI_GUID=与WECOM_PROTOCOL_GUID相同
```

## 上游迁移驱动

```env
WECOM_PROTOCOL_BACKEND=upstream
WECOM_PROTOCOL_UPSTREAM_BASE_URL=https://上游网关
WECOM_PROTOCOL_UPSTREAM_API_PATH=/api/qw/doApi
WECOM_PROTOCOL_UPSTREAM_TOKEN=上游Token
WECOM_PROTOCOL_UPSTREAM_CALLBACK_TOKEN=高强度回调Token
WECOM_PROTOCOL_STATE_KEY=持久化FernetKey
```

首次没有 `guid` 时可暂时留空 `WECOM_PROTOCOL_GUID`，仅调用 `/login/createDevice`。取得返回的 `guid` 后写入配置并重启网关；在完成绑定前，登录状态、发送和群管理方法都会被拒绝。

将上游回调地址配置为：

```text
https://本系统域名/callbacks/upstream
```

回调请求必须携带 `X-WECOM-UPSTREAM-CALLBACK-TOKEN`。下游业务回调使用 `X-WECOM-GATEWAY-TOKEN`，明文消息只存在于加密队列解密后的短暂转发过程中。

## 支持的方法

- `/login/createDevice`
- `/login/getLoginQrcode`
- `/login/checkLoginQrcode`
- `/login/verifyLoginQrcode`
- `/login/checkLogin`
- `/login/restoreDevice`
- `/login/logout`
- `/msg/sendText`
- `/room/modifyRoomName`

解散群、踢人、朋友圈和批量群发等高风险能力默认拒绝。

## Docker Compose

```bash
docker compose --profile protocol-gateway up -d wecom-protocol-gateway
```

专用镜像会安装固定版本的官方 CLI Linux 二进制。宿主机完成 `wecom-cli init`
后，将包含 `.encryption_key`、`bot.enc`、`mcp_config.enc` 的目录配置为
`WECOM_PROTOCOL_OFFICIAL_CLI_CONFIG_HOST_DIR`。该目录只读挂载且已被 Git 忽略。

该服务只加入 Compose 内部网络，不直接暴露宿主机端口。生产环境由反向代理仅开放回调入口，管理 API 保持内网访问。

## 原生协议驱动验收门槛

1. 仅使用企业自有测试账号和测试群获取行为样本。
2. 登录、心跳、断线恢复连续运行至少 72 小时。
3. 文本发送和改群名均能获得可关联回执，不允许仅凭 HTTP 成功判定送达。
4. 账号掉线、异地登录和风控提示必须进入系统告警。
5. 不记录二维码、会话密钥、Cookie、完整联系人和消息正文。
6. 任一异常可立即切回 Mock、官方群发任务或人工发送。
