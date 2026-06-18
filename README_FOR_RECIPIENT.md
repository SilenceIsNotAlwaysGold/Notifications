# Legal WeCom Automation - 交付说明

这是一个企业微信法务群自动化系统 MVP 后端项目，基于 FastAPI、SQLAlchemy、Alembic 和 APScheduler。

## 包内内容

- `app/`：应用源码
- `alembic/`、`alembic.ini`：数据库迁移
- `tests/`：自动化测试
- `docs/`：企微集成与客户准备清单
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

## Docker 启动

```bash
cp .env.example .env
docker compose up --build
```

## 上线前建议

```bash
pytest -q
alembic upgrade head
python -m app.cli check-config
```

生产环境请至少调整：

- `APP_ENV=production`
- `DB_AUTO_CREATE=false`
- `AUTH_ENABLED=true`
- `ADMIN_API_KEYS=your-long-secret-key`
- 使用外部持久化数据库和安全的密钥管理方案

## 注意事项

本交付包不包含本地 SQLite 数据库、`.env`、缓存文件、媒体存储内容或 Python 编译缓存。默认外部系统配置为 mock 模式；真实企业微信会话存档、真实媒体下载和真实 OCR 仍需按业务环境进一步接入。
