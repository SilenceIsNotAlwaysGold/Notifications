# Linux Android 外部群发送验收

## 定位

该方案用 Linux 服务器上的 Android 容器取代实体手机。Android 容器内运行官方企业
微信客户端和本项目自有的最小发送端，服务端继续使用已实现的
`/wecom/finder/api` 和兼容 WebSocket 协议。

这条路线不是企业微信官方发送 API，也不是 iPad 私有协议。它仍然是 Android 无障碍
UI 自动化，但不需要实体手机长期开机。

## 安全架构

```text
主业务 -> wecom-sender:8092 <- 127.0.0.1:8092 <- adb reverse <- 自有 Android 发送端
                                                        |
                                                        +-> 官方企业微信 App
```

- ADB 只绑定宿主机 `127.0.0.1:5555`，不得开放到公网。
- sidecar 只绑定宿主机 `127.0.0.1:8092`。Android 通过 `adb reverse` 访问，无需暴露
  WebSocket 公网入口。
- APK、账号、聊天数据和 Android `/data` 都不进入 Git。
- 仅使用隔离的“致和法务通知助手”账号，不授予企业管理权限。

## Linux 主机要求

ReDroid 需要 Linux 宿主机提供 binder 相关内核能力并以 `privileged` 运行。云服务器
如果不允许加载所需内核模块，该 profile 无法启动。官方 Google Android Emulator
容器可作为备选，但需要 `/dev/kvm` 或云主机支持嵌套虚拟化。

安装 ADB 和 scrcpy：

```bash
sudo apt-get install -y adb scrcpy
```

## 启动服务

`.env` 中配置：

```env
WECOM_SENDER_BACKEND=android
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

## 构建和安装 APK

先从仓库源码构建自有发送端。构建过程固定 Android Gradle Plugin、Gradle 和 Android
SDK 命令行工具版本，并执行 JVM 单测和 Android Lint：

```bash
scripts/build_android_sender.sh
```

构建脚本默认使用 `linux/amd64`，因为 Android 官方 Linux `aapt2` 工具按该架构发布；
Apple 芯片开发机由 Docker Desktop 自动模拟。可通过 `ANDROID_BUILD_PLATFORM` 覆盖。

输出位于 `dist/android-sender/zhihe-wecom-sender-debug.apk`，同目录 `SHA256SUMS`
用于交付校验。由交付人员将该 APK 与经审核的官方企业微信安装包放在 Git 忽略的
目录。不从未知网盘或自动更新链接下载 APK。

```bash
python -m wecom_sender_sidecar.device_cli \
  --serial 127.0.0.1:5555 install \
  --wecom-apk secrets/android-apks/wecom.apk \
  --companion-apk dist/android-sender/zhihe-wecom-sender-debug.apk
```

安装前工具会解析 APK 中的原生 ABI，与 Android 容器的
`ro.product.cpu.abilist` 比对。架构不兼容时直接停止。

## 启用自动化

```bash
python -m wecom_sender_sidecar.device_cli \
  --serial 127.0.0.1:5555 configure \
  --host-port 8092 \
  --device-port 8092
```

该命令只执行固定的 ADB 参数：

- 保留已有无障碍服务并启用自有发送端 `WeComAccessibilityService`。
- 配置 `tcp:8092 -> tcp:8092` 的 ADB reverse。
- 保持 Android 容器唤醒，将发送端加入待机白名单并启动。

使用 scrcpy 打开 Android 界面：

```bash
scrcpy -s 127.0.0.1:5555
```

1. 登录企业微信通知账号。
2. 自有发送端网关填写 `ws://127.0.0.1:8092`。
3. 设备 ID 填写 `WECOM_SENDER_ROBOT_ID`，保存并连接。
4. 打开 Android 无障碍设置，启用“致和法务企业微信发送”。

## 重启恢复

`adb reverse` 不会跨宿主机或 Android 容器重启保留。生产环境安装恢复单元，确保设备
启动后自动恢复反向端口和无障碍服务，并将企业微信切回前台。发送伴侣后台服务由应用
自身的 `BootReceiver` 在 Android 启动后恢复连接，不向 ADB 导出私有服务：

```bash
sudo install -m 0644 deploy/legal-wecom-android-sender.service \
  /etc/systemd/system/legal-wecom-android-sender.service
sudo systemctl daemon-reload
sudo systemctl enable --now legal-wecom-android-sender.service
```

恢复脚本默认读取 `/opt/legal-wecom-automation/.env`，使用
`WECOM_ANDROID_SERIAL`、`WECOM_ANDROID_ADB_BINARY` 和 `WECOM_SENDER_PORT`。设备尚未
完成启动时最多等待 120 秒；可通过 `WECOM_ANDROID_BOOT_WAIT_ATTEMPTS` 调整尝试次数。

```bash
systemctl status legal-wecom-android-sender.service
python -m wecom_sender_sidecar.device_cli \
  --serial "${WECOM_ANDROID_SERIAL}" check
curl http://127.0.0.1:8092/wecom/finder/health
```

## 验收

```bash
python -m wecom_sender_sidecar.device_cli \
  --serial 127.0.0.1:5555 check

curl http://127.0.0.1:8092/wecom/finder/health
```

`automation_ready=true` 表示设备、APK、无障碍和反向端口已就绪。sidecar 还必须返回
`device.online=true`。两项都通过后，在专用测试外部群发送一条无敏感信息，人工确认
群名、消息和回执一致。

## 现阶段边界

- 代码已完成 Linux Android 编排、自有发送端、APK 兼容检查和设备配置。
- 当前开发机为 macOS，ReDroid 只能在 Linux 宿主机实验，Compose 解析通过不等于真实
  发送通过。
- 企业微信升级可能改变控件树。正式交付前必须使用目标版本重做群搜索、文本输入、
  发送和失败回执回归。

参考：

- [ReDroid 官方文档](https://github.com/remote-android/redroid-doc)
- [Google Android Emulator Container Scripts](https://github.com/google/android-emulator-container-scripts)
- [Android AccessibilityService](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)
