# 企业微信原生协议静态分析记录

## 样本与边界

- 样本：官方企业微信 Android `5.0.9`，`versionCode=75230`。
- APK SHA-256：`2e7408948a8ddcf9d230506274cda832133a0ea2695d11d087b7450b458656ce`。
- 分析范围：APK 内登录相关 DEX 以及 ARM64 native 库。
- Pad 登录 native 库：`libwework_framework.so`，SHA-256
  `58a4722ccae2f2ea4c2495ca722edf9d7aaf3aa9f32fb216469f12e6ba0b331c`。
- 未读取 `/data/data/com.tencent.wework`，未提取账号 token、会话、数据库或业务数据。
- 未绕过扫码确认、身份证校验、人脸校验、设备校验或风控。

静态分析只证明字段、状态和客户端调用关系存在，不证明服务端允许第三方实现登录。

## 已验证的主账号二维码路径

### 企业微信 Pad 路径

`LoginQrCodeForAndroidPad` 的调用顺序为：

1. `GrandProfileService.StartGapHubLogic`
2. `GrandProfileService.getLoginQrCodeForPad`
3. `GrandProfileService.CheckQrCodeLoginForPad`
4. 必要时 `GrandProfileService.VerifyQrCodeForPad`
5. 成功后由官方客户端选择企业并建立会话

二维码检查失败后以 800ms 延迟继续轮询。二维码成功响应包含 token、二维码图片字节和
有效期相关值。客户端不会在扫码时直接认定登录成功。

`WwQrcodeLogin.CheckQrcodeData` 状态：

| 值 | 含义 |
|---:|---|
| 0 | 未开始 |
| 1 | 登录进行中 |
| 2 | 登录成功 |
| 3 | 登录失败 |
| 4 | 拒绝 |
| 5-8 | 微信侧进行中/成功/失败/拒绝 |
| 10 | 需要额外身份校验 |

状态 10 会显示输入框并调用 `VerifyQrCodeForPad`。该步骤必须由账号本人正常完成。

`WwQrcodeLogin.CheckQrcodeData` 已验证字段：

| 编号 | 字段 | 类型 |
|---:|---|---|
| 1 | `status` | int32 |
| 2 | `vid` | uint64 |
| 3 | `nickName` | bytes |
| 4 | `iconUrl` | bytes |
| 5 | `logo` | bytes |
| 6 | `isBindWx` | bool |
| 7 | `wxInfo` | message |
| 8 | `gid` | uint64 |
| 9 | `tgt` | bytes |
| 10 | `sk1` | bytes |
| 11 | `corpbriefinfo` | message |
| 12 | `qrkey` | bytes |
| 13 | `easykey` | bytes |

实验代码只返回非敏感字段以及会话材料是否存在，不返回或持久化
`tgt/sk1/qrkey/easykey` 的内容。

### Native 边界

Pad JNI 位于 `libwework_framework.so`：

| JNI 方法 | 地址 |
|---|---:|
| `nativeStartGapHubLogic` | `0x1225ea4` |
| `nativeVerifyQrCodeForPad` | `0x1228260` |
| `nativeGetLoginQrCodeForPad` | `0x1228430` |
| `nativeCheckQrCodeLoginForPad` | `0x1228594` |
| `nativeStopGapHubLogic` | `0x1226104` |

`nativeGetLoginQrCodeForPad` 的 Java 参数顺序已确认是
`handle, type, value, token, callback`。JNI 构造内部异步任务后交给通用任务调度器；调度器
入参中的常量 `7` 目前只能确认是内部类别索引，不能据此认定为网络命令号。

### Java/JNI 调用合同

| 操作 | 输入 | 回调 |
|---|---|---|
| 启动 GapHub | `handle` | `(errorCode, token, strings[])`；另有 `(errorCode, bytes)` |
| 获取二维码 | `handle, type, targetVid, token` | `(errorCode, keepSeconds, auxiliaryValue, qrImageBytes)` |
| 检查二维码 | `handle` | `(errorCode, errorMessage, CheckQrcodeData)` |
| 身份校验 | `handle, VerifyRequest` | `(errorCode, authErrorBytes)` |
| Gap 推送检查 | `handle, empty request` | `(errorCode, errorMessage, LoginAuthError)` |

Pad 页面调用 `StartGapHubLogic` 前先检查系统网络，并注册固定 `2000ms` 超时任务。超时会
调用 `StopGapHubLogic` 并回到二维码失败流程。主回调到达后页面取消超时、保存 token 并
继续获取二维码；`strings[]` 未被该页面读取。辅助 bytes 回调只记录 errorCode。Java 页面
没有把任一启动回调直接解释为账号在线或消息通道可用。

普通 Pad 登录页面传 `type=0`、`targetVid=0`；解锁页面覆盖为 `type=3` 并传入待解锁
账号的 vid。获取二维码回调第二个 long 值被页面作为二维码有效秒数使用。第三个 long
值在该页面没有使用，当前只记为辅助值。

`VerifyRequest` 原始类为 `ji40`：

| 编号 | 类型 | 已验证行为 |
|---:|---|---|
| 1 | `CliInfoProtocol.CliInfo` | 可选，页面未设置 |
| 2 | bytes | 可选，语义未确认 |
| 3 | bytes | 页面将用户输入按 UTF-8 原样写入 |

`OnGapPushCheckStatusForPad` 的请求类 `ii40` 是空 protobuf。它是状态检查触发器，不是
登录凭证。状态推送与 800ms 主动轮询均存在，后续实现不能只依赖其中一条路径。

库内存在 `GapHubLogicTCP`、ECC 会话、心跳和登录专用 token 相关实现，并包含
`gap.work.weixin.qq.com`、`gap6.work.weixin.qq.com`、`gp.work.weixin.qq.com`、
`i.work.weixin.qq.com`、`i6.work.weixin.qq.com`、`szfront.wxwork.qq.com` 等主机名。
这些字符串证明传输组件存在，不足以推导握手参数或证明第三方连接可用。

## 已排除的 iLink 路径

`libilink2.so` 暴露的真实 CGI 路径：

- `/ilink/ilinkapp/sys/ilinkapp_getloginqrcode`
- `/ilink/ilinkapp/sys/ilinkapp_checkloginqrcode`
- `/ilink/ilinkapp/sys/ilinkapp_autoauth`
- `/ilink/ilinkapp/sys/ilinkapp_manualauth`

Java/ZIDL 调用入口 `AuthManager.getLoginQrCodeAsync` 和
`AuthManager.checkLoginQrCodeAsync` 属于 `luggage-standalone-open-runtime-sdk`，服务于
小程序/开放运行时设备激活。它不是企业微信主账号登录入口，不能用于本项目发送账号登录。

iLink 二维码状态：`NO_SCAN(0)`、`SCANNED(1)`、`CONFIRMED(2)`、
`CANCELED(3)`、`EXPIRED(4)`。

已验证 protobuf 字段：

| 消息 | 字段 |
|---|---|
| `IlinkGetLoginQrCodeRequest` | `1 verify_scene:int`，`2 confirmation:bytes` |
| `IlinkGetLoginQrCodeResponse` | `1 path:string` |
| `IlinkCheckLoginQrCodeResponse` | `1 status:int`，`2 uin:long`，`3 nickname:string`，`4 avatar_url:string`，`5 confirmation:bytes` |
| `IlinkDeviceLoginRequest` | `1 product_id:int`，`2 device_id:string`，`3 signature:string`，`4 auth_type:int`，`5 signature_version:int`，`6 signature_timestamp:int` |
| `IlinkDeviceLoginResponse` | `1 ilink_sn:string`，`2 ilink_id:string`，`3 ilink_token:string`，`4 session:bytes` |

这些字段记录仅用于说明为什么排除该路径，不再作为下一阶段实现目标。

## 当前实现

`wecom_native_lab.protocol` 已实现：

- iLink 获取二维码请求的受限 protobuf 编码。
- 获取二维码与检查二维码响应的严格 protobuf 解码。
- 企业微信 Pad `CheckQrcodeData` 非敏感字段的严格 protobuf 解码。
- Pad 身份校验字段 3 和 Gap 推送空请求的受限编码。
- GapHub 启动回调的超时、错误、缺失 token 和 token 已观察状态模型。
- 未知状态、错误 wire type、截断字段、超长输入和非法 UTF-8 拒绝处理。
- iLink 与企业微信 Pad 两套状态枚举，避免把状态 10 错当成登录成功。
- 状态 2 只标记为 `qr_login_succeeded`，在获得账号在线回执前不标记为在线。

这些属于已验证协议结构，不列入 `implemented_capabilities`。实验 CLI 仍返回
`protocol_ready=false`。

`wecom_native_lab.transport` 另提供网络预检：默认只解析已确认的 GapHub 候选域名；仅在
显式提供白名单主机和经验证端口时执行零字节 TCP 连接。预检不发送握手、不提交账号
材料，并固定返回 `server_correlated=false`、`protocol_ready=false`。它只能用于排除
DNS 和基础网络问题，不能证明 GapHub 会话已经建立。
系统代理可能返回 `198.18.0.0/15` 等合成地址，因此解析成功本身也不作为真实服务地址
或可达性的证据。

## 尚未解决

1. `GapHubLogicTCP` 的最小初始化输入、传输帧边界和错误回调语义。
2. `VerifyRequest` 字段 2 的含义以及 `CliInfo` 是否由其他登录入口设置。
3. 长连接握手、会话恢复和心跳的服务端关联回执。
4. 企业微信账号会话与外部客户群消息协议的合法映射。
5. 服务端消息 ID 和外部群实际收件结果的双重验证。

下一里程碑是 `wecom_gaphub_connection_probe`：在隔离测试环境中验证 GapHub 启动的
错误回调、主机选择和可关联连接结果，不提交账号材料、不绕过身份校验。获得真实服务端
关联回执前，生产发送继续保持 Mock。
