# 金山文档 MCP 真实对接

## 传输方式

系统保留两种真实传输：

- `KDOCS_TRANSPORT=mcp`：直接调用 WPS Skill Hub MCP，当前项目优先使用。
- `KDOCS_TRANSPORT=gateway`：兼容历史封装网关。

MCP 使用 JSON-RPC `2025-03-26` 初始化会话，随后调用 `tools/call`。请求携带 `Authorization`、`X-Skill-Version`、`X-Client-Id` 和服务端返回的 `Mcp-Session-Id`。Token 只能写入部署环境变量，不得提交到仓库。

## 当前目标

```env
KDOCS_MODE=real
KDOCS_TRANSPORT=mcp
KDOCS_ACCESS_TOKEN=***
KDOCS_MCP_URL=https://mcp-center.wps.cn/skill_hub/mcp
KDOCS_MCP_SKILL_VERSION=1.3.6
KDOCS_MCP_CLIENT_ID=1c0529f7fbdcf731
KDOCS_DRIVE_ID=2619775069

KDOCS_ENFORCEMENT_FILE_ID=rNP24MBx3rMritppkrG7xxdBx8CtRoS4Z
KDOCS_ENFORCEMENT_WORKSHEET_ID=10
KDOCS_COURT_TIME_FILE_ID=2XZuheYq9xMWaLC6M2k1Bx54U98t13fsY
KDOCS_COURT_TIME_WORKSHEET_ID=1

KDOCS_JUDGMENT_PARENT_ID=vprpxois5rM4C2XeB2FK1xSyPWiUHNJM1
KDOCS_JUDGMENT_PARENT_PATH=

KDOCS_PAYMENT_FILE_ID=FNjVy6gETxMm6meVR3XAxxN4s5uc9ev7M
KDOCS_PAYMENT_WORKSHEET_ID=1
```

测试阶段已创建 `致和法务/判决书文件` 和 `致和法务/缴费登记.xlsx`。MCP real 模式要求三张表和文书目录全部配置，缺失时配置检查直接失败。

完成环境变量配置后运行只读预检：

```bash
uv run --with-requirements requirements.txt python scripts/check_kdocs_mcp.py
```

脚本只读取两张表的工作表信息和首行表头，不执行上传、写入或排序；任一表头与固定列映射不一致时返回非零退出码，阻止误写。

## 固定列映射

### 强制执行进度

目标工作表 `sheetId=10`，业务写入 0 至 24 列。主要自动字段：

| 列号 | 字段 | 自动来源 |
|---:|---|---|
| 2 | 原告主体 | OCR 原告 |
| 3 | 被告 | OCR 被告或案件债务人 |
| 5 | 文书执行类型 | 判决书、调解书、裁定书 |
| 6 | 上传文件 | 金山文件链接 |
| 8 | 应还款时间 | 案件到期日 |
| 18 | 民初案号 | OCR 或案件案号 |
| 19 | 总金额 | 案件总金额 |
| 20 | 已还欠款 | 案件已还金额 |
| 22 | 案件状态 | 案件状态 |
| 23 | 备注 | 文件名、识别摘要、复核状态、消息 ID |

写入前读取第 18 列。案号已存在时更新该行，不存在时追加到有效数据末尾。

### 开庭时间

目标工作表 `sheetId=1`。2026-07-20 的真实只读预检显示线上表当前只有 0 至 17 列有表头，因此只写这 18 列，忽略系统报告的空白扩展列。主要自动字段：

| 列号 | 字段 | 自动来源 |
|---:|---|---|
| 1 | 开庭时间 | 从 OCR 开庭时间拆出的日期 |
| 2 | 时间 | 从 OCR 开庭时间拆出的时分 |
| 3 | 公司（原告） | OCR 原告 |
| 4 | 民初案号 | OCR 或案件案号 |
| 5 | 被告 | OCR 被告或案件债务人 |
| 11 | 金额 | 案件总金额 |
| 12 | 代办事务 | 固定为开庭传票 |
| 14 | 备注 | OCR 摘要 |
| 16 | 传票 | 原文件链接 |
| 17 | 核对 | 已识别或待人工复核 |

字段映射 Excel 记录的第 18、19 列在线上已没有表头，系统不会向这两列写入；企业微信消息 ID 会并入第 14 列备注。新增后调用 `sheet.range_sort`，先按 B 列日期、再按 C 列时间升序排序，并保留首行表头。

## MCP 工具

- `sheet.get_sheets_info`：获取真实有效行范围。
- `sheet.get_range_data`：读取案号列并定位已有案件。
- `sheet.update_range_data`：按固定列号写入单元格。
- `sheet.range_sort`：开庭表按时间重排。
- `search_files`：上传前检查云盘内同名文件，避免覆盖已有文书。
- `upload_file`：上传重命名后的法律文书。
- `get_file_link`：补全上传文件链接。

同步请求中的 Base64 文件内容只存在于出站 MCP 请求，不写入 `document_sync_logs`。日志不保存 Token、请求头或私钥。

文书首次使用 `原告-被告{文书类型}.扩展名`。本地同步日志或金山云盘发现重名时追加案号、消息 ID，仍冲突时追加递增序号，不覆盖已有文件。
