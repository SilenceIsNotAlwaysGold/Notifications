import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_legal_wecom.db"
os.environ["DB_AUTO_CREATE"] = "true"
os.environ["AUTH_ENABLED"] = "false"
os.environ["ADMIN_API_KEYS"] = ""
os.environ["PUBLIC_ENDPOINTS"] = "/api/v1/health,/api/v1/health/detail"
os.environ["WECOM_SEND_MODE"] = "mock"
os.environ["WECOM_ARCHIVE_MODE"] = "mock"
os.environ["WECOM_ARCHIVE_SIDECAR_URL"] = ""
os.environ["WECOM_ARCHIVE_SEQ_FILE"] = "./test_wecom_archive_seq.txt"
os.environ["MEDIA_STORAGE_DIR"] = "./test_storage/media"
os.environ["MEDIA_DOWNLOAD_MODE"] = "mock"
os.environ["TENCENT_DOC_MODE"] = "mock"
os.environ["KDOCS_MODE"] = "mock"
os.environ["OCR_PROVIDER"] = "mock"
os.environ["OCR_SIDECAR_URL"] = ""
os.environ["LEGAL_EXTRACTION_MODE"] = "regex"
os.environ["LEGAL_LLM_BASE_URL"] = ""
os.environ["LEGAL_LLM_API_KEY"] = ""
os.environ["LEGAL_LLM_MODEL"] = ""
os.environ["OPS_BACKUP_DIR"] = "./test_storage/backups"
os.environ["OPS_DISK_FREE_MIN_GB"] = "0"
os.environ["OPS_WEBHOOK_URL"] = ""

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app

get_settings.cache_clear()

TEST_DB_PATH = Path("test_legal_wecom.db")
TEST_SEQ_PATH = Path("test_wecom_archive_seq.txt")
TEST_STORAGE_PATH = Path("test_storage")
TEST_DATABASE_URL = "sqlite:///./test_legal_wecom.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, future=True)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(autouse=True)
def reset_database():
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["AUTH_ENABLED"] = "false"
    os.environ["ADMIN_API_KEYS"] = ""
    os.environ["PUBLIC_ENDPOINTS"] = "/api/v1/health,/api/v1/health/detail"
    os.environ["WECOM_SEND_MODE"] = "mock"
    os.environ["WECOMAPI_BASE_URL"] = ""
    os.environ["WECOMAPI_TOKEN"] = ""
    os.environ["WECOMAPI_GUID"] = ""
    os.environ["WECOMAPI_MIN_INTERVAL_SECONDS"] = "0"
    os.environ["WECOM_CLI_BINARY"] = "wecom-cli"
    os.environ["WECOM_CLI_CONFIG_DIR"] = "~/.config/wecom"
    os.environ["WECOM_CLI_MIN_INTERVAL_SECONDS"] = "0"
    os.environ["WECOM_CLI_DAILY_LIMIT"] = "200"
    os.environ["WECOM_CLI_GROUP_DAILY_LIMIT"] = "10"
    os.environ["WECOM_ARCHIVE_MODE"] = "mock"
    os.environ["WECOM_ARCHIVE_SIDECAR_URL"] = ""
    os.environ["WECOM_ARCHIVE_SEQ_FILE"] = "./test_wecom_archive_seq.txt"
    os.environ["MEDIA_STORAGE_DIR"] = "./test_storage/media"
    os.environ["MEDIA_DOWNLOAD_MODE"] = "mock"
    os.environ["TENCENT_DOC_MODE"] = "mock"
    os.environ["TENCENT_DOC_BASE_URL"] = ""
    os.environ["TENCENT_DOC_ACCESS_TOKEN"] = ""
    os.environ["TENCENT_DOC_SHEET_ID"] = ""
    os.environ["KDOCS_MODE"] = "mock"
    os.environ["KDOCS_BASE_URL"] = ""
    os.environ["KDOCS_ACCESS_TOKEN"] = ""
    os.environ["KDOCS_SPACE_ID"] = ""
    os.environ["OCR_PROVIDER"] = "mock"
    os.environ["OCR_SIDECAR_URL"] = ""
    os.environ["OCR_ENABLE_REPROCESS"] = "true"
    os.environ["OCR_MAX_TEXT_LENGTH"] = "20000"
    os.environ["LEGAL_EXTRACTION_MODE"] = "regex"
    os.environ["LEGAL_LLM_BASE_URL"] = ""
    os.environ["LEGAL_LLM_API_KEY"] = ""
    os.environ["LEGAL_LLM_MODEL"] = ""
    os.environ["LEGAL_LLM_TIMEOUT_SECONDS"] = "30"
    os.environ["LEGAL_LLM_MAX_TEXT_LENGTH"] = "16000"
    os.environ["LEGAL_LLM_MIN_CONFIDENCE"] = "0.75"
    os.environ["LEGAL_LLM_FALLBACK_TO_REGEX"] = "true"
    os.environ["OPS_BACKUP_DIR"] = "./test_storage/backups"
    os.environ["OPS_DISK_FREE_MIN_GB"] = "0"
    os.environ["OPS_WEBHOOK_URL"] = ""
    get_settings.cache_clear()
    from app.adapters.wecomapi import WeComApiAdapter
    from app.adapters.wecom_cli import WeComCliAdapter

    WeComApiAdapter.reset_safety_state()
    WeComCliAdapter.reset_safety_state()
    if TEST_SEQ_PATH.exists():
        TEST_SEQ_PATH.unlink()
    if TEST_STORAGE_PATH.exists():
        import shutil

        shutil.rmtree(TEST_STORAGE_PATH)
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def pytest_sessionfinish(session, exitstatus):
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    if TEST_SEQ_PATH.exists():
        TEST_SEQ_PATH.unlink()
    if TEST_STORAGE_PATH.exists():
        import shutil

        shutil.rmtree(TEST_STORAGE_PATH)
