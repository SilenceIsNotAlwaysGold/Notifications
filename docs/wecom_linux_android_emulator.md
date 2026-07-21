# Linux Android 外部群发送验收

## 定位

该方案用 Linux 服务器上的 Android 容器取代实体手机。Android 容器内运行官方
企业微信客户端和自动化辅助程序，服务端继续使用已实现的
`/wecom/finder/api` 和 WorkTool WebSocket 协议。

这条路线不是企业微信官方发送 API，也不是 iPad 私有协议。它仍然是 Android
无障碍 UI 自动化，但不需要实体手机长期开机。

## 安全架构

```text
主业务 -> wecom-sender:8092 <- 127.0.0.1:8092 <- adb reverse <- Android WorkTool
                                                        |
                                                        +-> 官方企业微信 App
```

- ADB 只绑定宿主机 `127.0.0.1:5555`，不得开放到公网。
- sidecar 只绑定宿为 `127.0.0.1:8092`。Android 通过 `adb reverse` 访问，
  无需暴露 WebSocket 公网入口。
- APK、账号、聊天数据和 Android `/data` 都不进入 Git。
- 仅使用隔离的“致和法务通知助手”账号，不授予企业管理权限。

## Linux 主机要求

ReDroid 需要 Linux 宿主机提供 binder 相关内核能力并以 `privileged` 运行。云服务器
如果不允许加载所需内核模块，该 profile 无法启动。官方 Google Android
Emulator 容器可作为备选，但需要 `/dev/kvm` 或云主机支持嵌套虚拟化。

安装 ADB 和 scrcpy：

```bash
sudo apt-get install -y adb scrcpy
```

## 启动服务

`.env` 中配置：

```env
WECOM_SENDER_BACKEND=worktool
WECOM_SENDER_API_TOKEN=至少24位的高强度随机Token
WECOM_SENDER_ROBOT_ID=至少24位的高强度随机设备ID
WECOM_SENDER_TARGETS_JSON={"zhihe-legal":"致和法务执行群"}
WECOM_ANDROID_IMAGE=redroid/redroid:12.0.0-latest
WECOM_ANDROID_SERIAL=127.0.0.1:5555
```

```bash
docker compose -f docker-compose.yml -f docker-compose.android.yml \
  --profile android-sender --profile android-emulator \
  up -d wecom-sender wecom-android
adb connect 127.0.0.1:5555
```

主生产 `docker-compose.yml` 仍然只暴露 API 端口。仅在显式加载
`docker-compose.android.yml` 时，ADB 和 sidecar 才会映射到本机回环地址。

## 安装 APK

由交付人员将经审核的安装包放在 Git 忽略的 `secrets/android-apks/` 目录。不从未知
网盘或自动更新链接下载 APK。

```bash
python -m wecom_sender_sidecar.device_cli \
  --serial 127.0.0.1:5555 install \
  --wecom-apk secrets/android-apks/wecom.apk \
  --companion-apk secrets/android-apks/worktool.apk
```

安装前工具会解析 APK 中的原生 ABI，与 Android 容器的
`ro.product.cpu.abilist` 比对。架构不兼容时直接停止，不会在安装后才静默崩溃。

## 启用自动化

```bash
python -m wecom_sender_sidecar.device_cli \
  --serial 127.0.0.1:5555 configure \
  --host-port 8092 \
  --device-port 8092
```

该命令只执行固定的 ADB 参数：

- 保留已有无障碍服务并启用 WorkTool `WeworkService`。
- 配置 `tcp:8092 -> tcp:8092` 的 ADB reverse。
- 保持 Android 容器唤醒，将辅助程序加入待机白名单并启动。

使用 scrcpy 打开 Android 界面：

```bash
scrcpy -s 127.0.0.1:5555
```

1. 登录企业微信通知账号。
2. WorkTool Host 填写 `http://127.0.0.1:8092`。
3. WorkTool 链接号填写 `WECOM_SENDER_ROBOT_ID`。
4. 仅开启发送文本所需的最小功能。

## 验收

```bash
python -m wecom_sender_sidecar.device_cli \
  --serial 127.0.0.1:5555 check

curl http://127.0.0.1:8092/wecom/finder/health
```

`automation_ready=true` 表示设备、APK、无障碍和反向端口已就绪。sidecar 还必须
返回 `device.online=true`。这两项都通过后，在专用测试外部群发送一条无敏感信息，
人工确认群名、消息和回执一致。

## 现阶段边界

- 代码已完成 Linux Android 编排、APK 兼容检查和设备配置。
- 当前开发机为 macOS，ReDroid 只能在 Linux 宿主机实验，不把 Compose 解析通过冒充为真实发送通过。
- 公开 WorkTool 2.8.1 针对旧版企业微信，正式交付前必须用目标企业微信版本重做控件树回归。

参考：

- [ReDroid 官方文档](https://github.com/remote-android/redroid-doc)
- [Google Android Emulator Container Scripts](https://github.com/google/android-emulator-container-scripts)
- [WorkTool](https://github.com/gallonyin/worktool)
