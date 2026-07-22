# 企业微信原生协议实验环境

## 目标

`native_lab` 用于专用测试账号的洁净室互操作研究。它与生产提醒、案件数据库和真实群
完全隔离，第一阶段只验证设备注册、二维码登录、心跳、测试群发现和单条测试文本回执。

该模式不是生产发送通道，也不表示企业微信私有协议已经实现。

## 强制边界

- `WECOM_PROTOCOL_NATIVE_LAB_ENABLED=true` 必须显式开启。
- 必须配置持久化 `WECOM_PROTOCOL_STATE_KEY`，实验状态使用 Fernet 加密。
- 账号 guid 必须以 `lab-` 开头。
- 所有目标群 ID 必须以 `test-` 开头。
- 真实发送默认关闭；放行后消息仍必须以 `[PROTOCOL-LAB]` 开头。
- 传输命令通过子进程标准输入传递，不把消息正文放进命令行参数。
- 网关审计只保存账号和目标哈希，不保存消息正文或会话密钥。

## 配置

```env
WECOM_PROTOCOL_BACKEND=native_lab
WECOM_PROTOCOL_API_TOKEN=独立实验Token
WECOM_PROTOCOL_GUID=lab-zhihe-sender-001
WECOM_PROTOCOL_ROOM_IDS_JSON={"zhihe-test":"test-external-room-001"}
WECOM_PROTOCOL_STATE_KEY=独立FernetKey

WECOM_PROTOCOL_NATIVE_LAB_ENABLED=true
WECOM_PROTOCOL_NATIVE_LAB_BINARY=wecom-native-lab
WECOM_PROTOCOL_NATIVE_LAB_STATE=/app/data/native-lab-state.enc
WECOM_PROTOCOL_NATIVE_LAB_TIMEOUT_SECONDS=20
WECOM_PROTOCOL_NATIVE_LAB_ALLOW_SEND=false
WECOM_PROTOCOL_NATIVE_LAB_GUID_PREFIX=lab-
WECOM_PROTOCOL_NATIVE_LAB_ROOM_PREFIX=test-
WECOM_PROTOCOL_NATIVE_LAB_MESSAGE_PREFIX=[PROTOCOL-LAB]
```

实验网关必须使用独立容器、独立 Token、独立状态文件，不能复用生产 `api` 服务的
数据库、企业微信归档 Secret 或金山文档凭证。

## 诊断

```bash
curl http://127.0.0.1:8092/api/qw/lab/status \
  -H 'WECOM-TOKEN: 实验Token'

curl -X POST http://127.0.0.1:8092/api/qw/capabilities/probe \
  -H 'WECOM-TOKEN: 实验Token'
```

当前脚手架应返回：

```json
{
  "transport": "native_lab_scaffold",
  "protocol_ready": false,
  "implemented_capabilities": [],
  "verified_protocol_facts": [
    "wecom_pad_qr_state_machine",
    "wecom_pad_check_qrcode_schema",
    "wecom_pad_jni_boundary",
    "wecom_gaphub_transport_hosts"
  ],
  "next_capability": "wecom_pad_transport_boundary"
}
```

只有底层传输返回服务端可关联回执后，能力才允许加入
`implemented_capabilities`。HTTP 200、本地入队或 UI 点击均不能作为送达证明。

APK 静态分析证据、二维码状态和 protobuf 字段见
[`wecom_native_protocol_findings.md`](./wecom_native_protocol_findings.md)。

## 测试账号流程

1. 创建不具备管理员权限的专用企业微信账号。
2. 创建无真实客户、案件、手机号和文书的外部测试群。
3. 账号仅加入该测试群，不加入现有法务群。
4. 登录阶段由账号本人扫码或输入验证码，不向系统提供密码。
5. 依次验收设备注册、二维码状态、在线心跳、群发现、单条文本回执。
6. 登录和心跳稳定后，才可临时设置
   `WECOM_PROTOCOL_NATIVE_LAB_ALLOW_SEND=true`。
7. 连续运行 72 小时并完成断线恢复后，再讨论与业务提醒集成。

## 停止条件

出现身份验证绕过要求、账号风控、非测试群数据、无法确认的服务端回执或客户端协议
重大升级时，立即停止实验并保持生产 `WECOM_SEND_MODE=mock`。
