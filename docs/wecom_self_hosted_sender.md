# 企业微信外部群自托管发送方案

## 结论

本项目采用“官方会话内容存档负责读取，自托管 Android RPA 负责发送”的双通道架构。发送端操作官方企业微信 Android 客户端，不实现或逆向 iPad 私有协议。

当前已实现自托管网关：

- 主服务仍使用 `WECOM_SEND_MODE=wecomapi`，无需改变现有提醒业务代码。
- 网关提供兼容的 `/wecom/finder/api` HTTP 接口。
- Android 客户端通过 `/webserver/wework/{robot_id}` 主动建立 WebSocket 长连接。
- 目标群必须在服务端白名单中，默认禁止任意群名发送。
- 网关等待 Android 客户端真实执行回执；设备离线、执行失败和超时都会返回失败。
- 支持 `mock` 模式，不连接手机也能完成业务验收。

## 开源项目调研

### WorkTool

- 仓库：<https://github.com/gallonyin/worktool>
- 许可证：Apache-2.0。
- 技术：Android `AccessibilityService` 驱动官方企业微信客户端。
- 源码中包含外部群识别、按群名进入、文本发送、群名修改和 WebSocket 指令回执。
- 公开源码版本为 `2.8.1`，兼容列表截至企业微信 `4.1.10`。仓库 README 提供的新安装包声称兼容企业微信 `5.0.8`，但对应适配源码未同步到公开代码，不能把新安装包的兼容性等同于开源源码兼容性。

适合作为手机端参考底座，但必须在专用测试手机上重新适配当前企业微信版本并完成回归测试。

### 其他候选

| 项目 | 结论 |
| --- | --- |
| `xing653245/WeChat-Work-Hook` | 仓库只有 README，核心程序为商业授权下载，不是可二开的开源实现。 |
| `apachecn/wxwork_pc_api` | 核心功能位于预编译 DLL，仅支持企业微信 `3.0.27.2701`，版本过旧。 |
| `xlrpa/FlowBot` | 主要是通用 Auto.js/无障碍框架，企业微信能力只见于文档；许可证附加“禁止商业使用”，不适合交付。 |
| `openatx/uiautomator2` | 成熟的 Android 自动化基础设施，可用于设备联调或应急脚本，但没有现成企业微信业务逻辑。 |
| `pywinauto` / `FlaUI` | Windows UI 自动化基础设施，许可证友好；企业微信桌面端控件可访问性仍需实机验证。 |

## 启动 mock 网关

在独立终端设置：

```env
WECOM_SENDER_BACKEND=mock
WECOM_SENDER_API_TOKEN=生成的高强度随机Token
WECOM_SENDER_ROBOT_ID=robot-zhihe-001
WECOM_SENDER_TARGETS_JSON={"zhihe-legal":"致和法务执行群"}
```

启动：

```bash
uvicorn wecom_sender_sidecar.main:app --host 127.0.0.1 --port 8092
```

主服务配置：

```env
WECOM_SEND_MODE=wecomapi
WECOMAPI_BASE_URL=http://127.0.0.1:8092
WECOMAPI_API_PATH=/wecom/finder/api
WECOMAPI_TOKEN=与WECOM_SENDER_API_TOKEN相同
WECOMAPI_GUID=与WECOM_SENDER_ROBOT_ID相同
```

管理端“发送目标 ID”填写白名单键，例如 `zhihe-legal`，而不是直接填写可变的群名。

## 连接 Android 客户端

1. 将 `WECOM_SENDER_BACKEND` 改为 `worktool`。
2. 使用专用 Android 手机登录“致和法务通知助手”企业微信账号。
3. 手机端客户端的 Host 指向公网 `wss://你的域名`，链接号填写 `WECOM_SENDER_ROBOT_ID`。
4. 反向代理必须把 `/webserver/wework/` 的 WebSocket Upgrade 透传到网关端口。
5. 打开 `GET /wecom/finder/health`，确认 `device.online=true`。
6. 仅在测试外部群发送无敏感内容的消息，确认目标群和回执后再灰度。

公开 WorkTool 源码当前不能直接保证兼容企业微信 5.x。手机端正式交付前需要建立我们自己的 fork，移除统计 SDK 和第三方更新接口，并根据实机控件树更新选择器。

不使用实体手机时，可在 Linux 服务器上启动 Android 容器，复用同一个 WorkTool
WebSocket 协议。部署、APK ABI 预检和 ADB 反向端口步骤见
[企业微信 Linux Android 外部群发送验收](wecom_linux_android_emulator.md)。

## 安全边界

- 专用账号不授予管理员权限，只加入需要提醒的法务群。
- `WECOM_SENDER_ROBOT_ID` 同时承担设备连接凭证作用，必须使用高熵随机值且只通过 WSS 暴露。
- `WECOM_SENDER_TARGETS_JSON` 默认白名单模式；生产环境不得开启 `WECOM_SENDER_ALLOW_RAW_TARGETS`。
- 只发送文本提醒，不通过 RPA 通道传输判决书、身份证明或收款资料。
- 主服务已有最小发送间隔、每日上限和连续失败熔断，生产环境不可关闭。
- 该方案不是企业微信官方发送 API，仍存在客户端升级导致失效、账号限制和平台规则风险，必须使用专用测试账号灰度。
