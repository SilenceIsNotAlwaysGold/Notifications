import httpx
from sqlalchemy import select

from app.adapters.wecom_archive import WeComArchiveAdapter
from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.group_message import GroupMessage
from app.models.legal_event import LegalEvent
from app.models.reminder import Reminder
from app.utils.seq_store import SeqStore


def create_case(client):
    response = client.post(
        "/api/v1/legal/cases",
        json={
            "case_no": "(2026)黔0281民初3118号",
            "debtor_name": "张三",
            "group_id": "group_001",
            "debtor_wecom_userid": "debtor_001",
            "lawyer_wecom_userid": "lawyer_001",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )
    assert response.status_code == 200


def test_normalize_text_message_success():
    normalized = WeComArchiveAdapter().normalize_message(
        {
            "seq": 1,
            "msgid": "msg_001",
            "roomid": "group_001",
            "from": "user_001",
            "msgtype": "text",
            "text": {"content": "测试文本"},
            "msgtime": 1780300000000,
        }
    )

    assert normalized["group_id"] == "group_001"
    assert normalized["sender_id"] == "user_001"
    assert normalized["msg_type"] == "text"
    assert normalized["content"] == "测试文本"
    assert normalized["file_url"] is None
    assert normalized["raw_payload_json"]["msgid"] == "msg_001"
    assert normalized["received_at"].endswith("+08:00")


def test_normalize_file_pdf_success():
    normalized = WeComArchiveAdapter().normalize_message(
        {
            "seq": 2,
            "roomid": "group_001",
            "from": "user_001",
            "msgtype": "file",
            "file": {"filename": "判决书.pdf", "md5sum": "abc", "filesize": 123},
        }
    )

    assert normalized["msg_type"] == "pdf"
    assert normalized["content"] is None


def test_normalize_link_message_success():
    normalized = WeComArchiveAdapter().normalize_message(
        {
            "seq": 3,
            "roomid": "group_001",
            "from": "user_001",
            "msgtype": "link",
            "link": {
                "title": "腾讯文档",
                "description": "案件台账",
                "link_url": "https://docs.qq.com/sheet/example",
            },
        }
    )

    assert normalized["msg_type"] == "link"
    assert normalized["content"] == "腾讯文档\n案件台账\nhttps://docs.qq.com/sheet/example"


def test_replay_processes_text_message_and_creates_business_records(client, db_session):
    create_case(client)
    response = client.post(
        "/api/v1/legal/wecom-archive/replay",
        json={
            "messages": [
                {
                    "seq": 1,
                    "msgid": "msg_001",
                    "roomid": "group_001",
                    "from": "user_001",
                    "msgtype": "text",
                    "text": {"content": "案件(2026)黔0281民初3118号需要缴费400元，7天内完成"},
                    "msgtime": 1780300000000,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "pulled": 1,
        "processed": 1,
        "failed": 0,
        "skipped": 0,
        "discovered": 0,
        "identified": 0,
        "last_seq": 1,
    }

    message = db_session.scalar(select(GroupMessage).where(GroupMessage.group_id == "group_001"))
    event = db_session.scalar(select(LegalEvent).where(LegalEvent.group_message_id == message.id))
    reminders = list(db_session.scalars(select(Reminder).where(Reminder.reminder_type == "payment_tracking")).all())

    assert message.sender_id == "user_001"
    assert message.msg_type == "text"
    assert event.event_type == "payment_notice"
    assert len(reminders) == 7


def test_replay_with_ocr_processes_media_text_and_kdocs_logs(client, db_session, monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "mock")
    monkeypatch.setenv("KDOCS_MODE", "mock")
    get_settings.cache_clear()
    create_case(client)

    response = client.post(
        "/api/v1/legal/wecom-archive/replay-with-ocr",
        json={
            "messages": [
                {
                    "seq": 10,
                    "msgid": "msg_dev_judgment",
                    "roomid": "group_001",
                    "from": "user_001",
                    "msgtype": "file",
                    "file": {"filename": "判决书.pdf", "md5sum": "abc", "filesize": 123},
                    "msgtime": 1780300000000,
                }
            ],
            "ocr_text_by_msgid": {
                "msg_dev_judgment": "民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三"
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["processed"] == 1
    assert data["ocr_processed"] == 1
    assert data["ocr_failed"] == 0
    assert data["ocr_results"][0]["event_type"] == "judgment"
    assert data["ocr_results"][0]["document_type"] == "判决书"
    assert data["ocr_results"][0]["plaintiff"] == "李四"
    assert data["ocr_results"][0]["defendant"] == "张三"
    assert data["ocr_results"][0]["requires_review"] is False

    sync_types = {log.sync_type for log in db_session.scalars(select(DocumentSyncLog)).all()}
    assert "legal_document_upload" in sync_types
    assert "enforcement_progress" in sync_types
    get_settings.cache_clear()


def test_replay_demo_creates_case_and_full_mock_business_loop(client, db_session, monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "mock")
    monkeypatch.setenv("KDOCS_MODE", "mock")
    get_settings.cache_clear()

    response = client.post("/api/v1/legal/wecom-archive/replay-demo")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["case_no"] == "(2026)黔0281民初3118号"
    assert data["processed"] == 4
    assert data["ocr_processed"] == 4
    assert data["ocr_failed"] == 0

    sync_types = {log.sync_type for log in db_session.scalars(select(DocumentSyncLog)).all()}
    assert {"legal_document_upload", "enforcement_progress", "court_time", "payment_registration"}.issubset(sync_types)
    reminders = list(db_session.scalars(select(Reminder).where(Reminder.reminder_type == "payment_tracking")).all())
    assert len(reminders) == 7
    get_settings.cache_clear()


def test_pull_mock_mode_returns_empty_without_error(client):
    seq_path = get_settings().wecom_archive_seq_file
    SeqStore(seq_path).path.unlink(missing_ok=True)

    response = client.post("/api/v1/legal/wecom-archive/pull")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "pulled": 0,
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "discovered": 0,
        "identified": 0,
        "last_seq": 0,
    }


def test_fetch_real_mode_uses_sidecar(monkeypatch):
    monkeypatch.setenv("WECOM_ARCHIVE_MODE", "real")
    monkeypatch.setenv("WECOM_CORP_ID", "wwxxxx")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "archive-secret")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "/secure/private.pem")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "1")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "http://127.0.0.1:9001/wecom-archive")
    get_settings.cache_clear()

    def fake_post(url, json=None, timeout=None):
        assert url == "http://127.0.0.1:9001/wecom-archive/messages"
        assert json["seq"] == 100
        assert json["limit"] == 20
        assert json["corp_id"] == "wwxxxx"
        assert json["archive_secret"] == "archive-secret"
        assert json["private_key_path"] == "/secure/private.pem"
        assert json["public_key_ver"] == "1"
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"messages": [{"seq": 101, "msgtype": "text", "text": {"content": "ok"}}]}, request=request)

    monkeypatch.setattr("app.adapters.wecom_archive.httpx.post", fake_post)

    messages = WeComArchiveAdapter().fetch_messages(seq=100, limit=20)

    assert messages == [{"seq": 101, "msgtype": "text", "text": {"content": "ok"}}]
    get_settings.cache_clear()


def test_fetch_real_mode_without_sidecar_raises(monkeypatch):
    monkeypatch.setenv("WECOM_ARCHIVE_MODE", "real")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "")
    get_settings.cache_clear()

    try:
        WeComArchiveAdapter().fetch_messages(seq=0, limit=1)
    except RuntimeError as exc:
        assert "WECOM_ARCHIVE_SIDECAR_URL" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    finally:
        get_settings.cache_clear()


def test_seq_store_missing_file_defaults_to_zero(tmp_path):
    seq_store = SeqStore(str(tmp_path / "missing_seq.txt"))

    assert seq_store.read() == 0


def test_seq_store_write_then_read_latest_value(tmp_path):
    seq_store = SeqStore(str(tmp_path / "seq.txt"))

    seq_store.write(12345)

    assert seq_store.read() == 12345
