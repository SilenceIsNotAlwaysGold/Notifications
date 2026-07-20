# Legal WeCom Automation - 交付说明

这是一个企业微信法务群自动化系统 MVP 后端项目，基于 FastAPI、SQLAlchemy、Alembic 和 APScheduler。

## 包内内容

- `app/`：应用源码
- `alembic/`、`alembic.ini`：数据库迁移
- `tests/`：自动化测试
- `docs/`：企微集成、客户准备清单和交付验收说明
- `README.md`：完整项目说明
- `.env.example`：环境变量模板
- `Dockerfile`、`docker-compose.yml`：容器化部署配置
- `scripts/`：本地运行、预检和迁移检查脚本

## 本地启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

启动后访问：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

管理端：

```text
http://127.0.0.1:8000/admin/
```

第一版 mock 验收可在管理端“消息”页点击“一键生成演示数据”，或调用：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/legal/wecom-archive/replay-demo
```

也可以运行冒烟验收脚本：

```bash
scripts/smoke_demo.sh
```

## Docker 启动

```bash
cp .env.example .env
mkdir -p secrets
docker compose up --build -d
docker compose ps
```

仅启用可选企业微信机器人 sidecar：

```bash
docker compose --profile robot up --build -d
```

手工执行一致性备份：

```bash
docker compose --profile operations run --rm backup
```

恢复前应停止 API，然后显式校验并恢复指定备份：

```bash
docker compose stop api
docker compose --profile operations run --rm backup \
  python -m app.ops.restore /app/backups/20260720T023000Z --force
docker compose up -d api
```

## 上线前建议

```bash
pytest -q
alembic upgrade head
python3 -m app.cli check-config
python3 scripts/acceptance_ocr_samples.py
python3 scripts/acceptance_wecom_sidecar_mock.py
```

或统一执行：

```bash
scripts/release_check.sh
```

生产环境请至少调整：

- `APP_ENV=production`
- `DB_AUTO_CREATE=false`
- `AUTH_ENABLED=true`
- `ADMIN_API_KEYS=your-long-secret-key`
- 使用外部持久化数据库和安全的密钥管理方案
- 安装 `deploy/legal-wecom-backup.service` 和 `.timer`，确认每日备份可恢复

## 注意事项

本交付包不包含本地 SQLite 数据库、`.env`、缓存文件、媒体存储内容、私钥、公钥、企业微信 SDK 二进制或 Python 编译缓存。默认外部系统配置为 mock 模式；仓库已内置企业微信官方 SDK backend，Linux x86 部署时运行 `scripts/install_wecom_sdk.sh` 安装官方 SDK，再按业务环境填写真实凭证。真实金山文档仍需配置 API 网关与目标表格 ID。

详细验收步骤见 `docs/delivery_acceptance.md`。
