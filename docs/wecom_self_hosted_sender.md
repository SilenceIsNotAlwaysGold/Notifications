# 企业微信外部群自托管发送方案

## 结论

本项目采用“官方会话内容存档负责读取，自托管 Android RPA 负责发送”的双通道架构。
发送端操作官方企业微信 Android 客户端，不实现或逆向 iPad 私有协议。

当前已实现自托管网关：

- 主服务仍使用 `WECOM_SEND_MODE=wecomapi`，无需改变提醒业务代码。
- 网关提供兼容的 `/wecom/finder/api` HTTP 接口。
- Android 客户端通过 `/webserver/wework/{robot_id}` 主动建立 WebSocket 长连接。
- 目标群必须在服务端白名单中，默认禁止任意群名发送。
- 网关等待 Android 客户端真实执行回执；设备离线、失败和超时都返回失败。
- 支持 `mock` 模式，不连接设备也能完成业务验收。

## 自有 Android 发送端

`android_sender_client/` 是本项目的最小发送客户端，不依赖第三方机器人 APK：

- 只连接配置的本机 `ws://127.0.0.1` 网关或远端 WSS 网关。
- 只接受单个群名、单条文本的 `type=203` 指令。
- 同时只执行一条命令；搜索结果不唯一时停止发送。
- 发送按钮点击后检查输入框是否清空，再返回成功回执。
- 不包含统计 SDK、云端更新、文件传输或聊天内容日志。

## 开源项目调研

WorkTool 的 Apache-2.0 公开源码展示了 AccessibilityService、群搜索和 WebSocket 回执
思路，但公开代码只明确适配到较旧企业微信版本，并包含本项目不需要的第三方能力。
它仅作为协议和控件操作参考，不再作为交付 APK。

其他候选中，PC Hook 项目依赖闭源 DLL 或固定旧版本；通用 Auto.js、uiautomator2 和
Windows UI 自动化框架没有可直接交付的企业微信业务实现。因此自有最小 Android
客户端是当前可控性更高的路径。

## 启动 mock 网关

```env
WECOM_SENDER_BACKEND=mock
WECOM_SENDER_API_TOKEN=生成的高强度随机Token
WECOM_SENDER_ROBOT_ID=robot-zhihe-001-32-characters-long
WECOM_SENDER_TARGETS_JSON={"zhihe-legal":"致和法务执行群"}
```

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

管理端“发送目标 ID”填写白名单键，例如 `zhihe-legal`，而不是直接填写可变群名。

## 连接 Android 客户端

1. 运行 `scripts/build_android_sender.sh` 构建自有发送端 APK。
2. 将 `WECOM_SENDER_BACKEND` 改为 `android`。
3. 使用专用 Android 设备或 Linux Android 容器登录通知账号。
4. 发送端网关填写 `ws://127.0.0.1:8092`；只有跨主机部署时才使用远端 WSS。
5. 设备 ID 填写 `WECOM_SENDER_ROBOT_ID`，启用发送端无障碍服务。
6. 打开 `GET /wecom/finder/health`，确认 `device.online=true`。
7. 仅在测试外部群发送无敏感内容，确认群名和回执后再灰度。

Linux Android 容器部署、APK ABI 预检和 ADB 反向端口步骤见
[企业微信 Linux Android 外部群发送验收](wecom_linux_android_emulator.md)。

## 安全边界

- 专用账号不授予管理员权限，只加入需要提醒的法务群。
- `WECOM_SENDER_ROBOT_ID` 承担设备连接凭证作用，必须使用高熵随机值；远端只通过 WSS。
- `WECOM_SENDER_TARGETS_JSON` 默认白名单模式，生产环境不得开启任意目标。
- 只发送文本提醒，不通过 RPA 通道传输判决书、身份证明或收款资料。
- 主服务的最小发送间隔、每日上限和连续失败熔断在生产环境不可关闭。
- 该方案不是企业微信官方发送 API，仍存在客户端升级、账号限制和平台规则风险，必须
  使用专用测试账号灰度。
