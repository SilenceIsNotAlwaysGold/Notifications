# 企业微信官方会话存档 SDK 部署

本项目通过仅监听 `127.0.0.1:9001` 的 sidecar 加载企业微信官方 Linux SDK。主服务通过 HTTP 调用 sidecar，不直接加载原生动态库。

## 安装

适用环境：Linux x86_64、OpenSSL 3。

```bash
scripts/install_wecom_sdk.sh
```

安装脚本下载官方 SDK v3.0，并校验固定 SHA256 与 MD5。动态库安装到 `wecom_archive_sidecar/sdk/`，该目录下的 SDK 文件不会进入 Git。

## 配置

主服务和 sidecar 使用同一份受限环境文件：

```env
WECOM_ARCHIVE_MODE=real
MEDIA_DOWNLOAD_MODE=real
WECOM_CORP_ID=wwxxxxxxxxxxxxxxxx
WECOM_ARCHIVE_SECRET=***
WECOM_ARCHIVE_PRIVATE_KEY_PATH=/etc/legal-wecom/private_key.pem
WECOM_ARCHIVE_PUBLIC_KEY_VER=1
WECOM_ARCHIVE_SIDECAR_URL=http://127.0.0.1:9001/wecom-archive
WECOM_ARCHIVE_SIDECAR_MOCK=false

WECOM_ARCHIVE_SIDECAR_BACKEND=wecom_archive_sidecar.sdk_backend:create_backend
WECOM_FINANCE_SDK_LIBRARY=/opt/legal-wecom-automation/wecom_archive_sidecar/sdk/libWeWorkFinanceSdk_C.so
WECOM_FINANCE_SDK_TIMEOUT_SECONDS=10
WECOM_ARCHIVE_MEDIA_MAX_BYTES=52428800
```

私钥文件权限应为 `600`，环境文件权限不高于 `600`。sidecar 不应监听公网地址。

## 启动与验收

```bash
uvicorn wecom_archive_sidecar.main:app --host 127.0.0.1 --port 9001
curl http://127.0.0.1:9001/wecom-archive/health
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/pull
```

企业微信只允许获取最近 5 天内的会话记录。生产环境应开启定时拉取并监控失败日志，避免数据过期。

## 法务群范围

企业微信侧的存档范围以员工为单位，本系统再以 `roomid` 白名单限制业务处理范围。真实拉取发现新群时，只记录群 ID 和发现时间，不保存消息正文。管理员可发送 `#群名识别群 群名称` 特殊消息自动更新系统内显示名称，然后在管理后台“归档群”页面将目标群设为“已启用”，随后重新发送测试消息。命名消息不会改变启用状态，也不会进入媒体下载、OCR 或文档同步。

官方接口文档：[获取会话内容](https://developer.work.weixin.qq.com/document/path/91774)。
