# 金山文档封装网关协议

本协议仅用于兼容 `KDOCS_MODE=real` 且 `KDOCS_TRANSPORT=gateway` 的历史部署。当前项目优先使用 `KDOCS_TRANSPORT=mcp`，见 `docs/kdocs_mcp_integration.md`。

```env
KDOCS_BASE_URL=https://your-kdocs-gateway.example.com
KDOCS_ACCESS_TOKEN=***
KDOCS_SPACE_ID=***
```

所有请求都会携带：

```http
Authorization: Bearer ${KDOCS_ACCESS_TOKEN}
```

## 表格写入接口

除文件上传外，主服务使用 JSON POST：

```http
POST {KDOCS_BASE_URL}/kdocs/{operation}
Content-Type: application/json
```

当前 operation：

- `update_case_status`
- `update_paid_amount`
- `append_archive_row`
- `sync_case_snapshot`
- `append_court_time_row`
- `append_enforcement_row`
- `append_payment_registration_row`

示例：

```json
{
  "tenant_id": null,
  "space_id": "space_001",
  "sheet_id": "致和法务/开庭时间",
  "sort_by": "开庭时间",
  "row": {
    "案号": "(2026)黔0281民初3118号",
    "开庭时间": "2026-07-02T15:00:00+08:00"
  }
}
```

## 文件上传接口

文书上传使用 multipart POST：

```http
POST {KDOCS_BASE_URL}/kdocs/files/upload
Content-Type: multipart/form-data
```

字段：

- `space_id`
- `folder_id`
- `target_filename`
- `metadata`：JSON 字符串
- `file`：文件内容，文件名为 `target_filename`

## 响应约定

HTTP 状态码 `< 400` 且 JSON 中 `success` 不为 `false` 时，主服务认为同步成功。

成功示例：

```json
{
  "success": true,
  "row_id": "row_001"
}
```

文件上传成功示例：

```json
{
  "success": true,
  "file_id": "file_001",
  "url": "https://kdocs.example.com/file_001"
}
```

失败示例：

```json
{
  "success": false,
  "error": "invalid sheet mapping"
}
```

失败会写入 `document_sync_logs.status=failed`，可通过 `/api/v1/legal/document-sync-logs/{id}/retry` 重试。

## 安全边界

同步日志只保存业务 payload 和网关 response，不保存 `Authorization` header、token、Secret、私钥。
