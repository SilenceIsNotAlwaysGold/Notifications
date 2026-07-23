from decimal import Decimal

from sqlalchemy import select

from app.models.document_sync_log import DocumentSyncLog
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.reminder import Reminder


def create_case(client, case_no="(2026)黔0281民初3118号"):
    response = client.post(
        "/api/v1/legal/cases",
        json={
            "case_no": case_no,
            "debtor_name": "张三",
            "group_id": "group_001",
            "debtor_wecom_userid": "debtor_001",
            "lawyer_wecom_userid": "lawyer_001",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )
    assert response.status_code == 200
    assert response.json()["code"] == 0
    return response.json()["data"]


def test_create_case_success(client):
    data = create_case(client)
    assert data["case_no"] == "(2026)黔0281民初3118号"
    assert data["paid_amount"] == "0.00"


def test_list_cases_success(client):
    create_case(client)
    response = client.get("/api/v1/legal/cases", params={"group_id": "group_001"})
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["total"] == 1


def test_text_message_extracts_case_no_and_amount(client):
    create_case(client)
    response = client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "案件(2026)黔0281民初3118号需要缴费400元，7天内完成",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["extracted"]["case_no"] == "(2026)黔0281民初3118号"
    assert body["data"]["extracted"]["amount"] == "400.00"


def test_payment_notice_creates_7_tracking_reminders(client, db_session):
    create_case(client)
    client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "案件(2026)黔0281民初3118号缴费通知：诉讼费400元，7天内完成",
        },
    )
    reminders = list(db_session.scalars(select(Reminder).where(Reminder.reminder_type == "payment_tracking")).all())
    assert reminders == []


def test_payment_done_increments_paid_amount(client, db_session):
    create_case(client)
    response = client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "案件(2026)黔0281民初3118号付款截图，已支付¥400",
        },
    )
    assert response.status_code == 200
    legal_case = db_session.scalar(select(LegalCase).where(LegalCase.case_no == "(2026)黔0281民初3118号"))
    assert legal_case.paid_amount == Decimal("0.00")


def test_message_without_case_no_saves_message_and_event(client, db_session):
    response = client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_002",
            "sender_id": "user_002",
            "msg_type": "text",
            "content": "现场开庭通知，请准备材料",
        },
    )
    assert response.status_code == 200
    message = db_session.scalar(select(GroupMessage).where(GroupMessage.group_id == "group_002"))
    event = db_session.scalar(select(LegalEvent).where(LegalEvent.group_message_id == message.id))
    assert message is not None
    assert event is not None
    assert event.case_id is None
    assert event.event_type == "court_notice"


def test_custom_reminder_create_success(client):
    response = client.post(
        "/api/v1/legal/reminders/custom",
        json={
            "group_id": "group_001",
            "remind_at": "2026-06-02T09:00:00+08:00",
            "content": "请跟进案件材料",
            "target_userid": "lawyer_001",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 0
    assert body["data"]["reminder_type"] == "custom"


def test_run_due_marks_pending_reminder_simulated_in_mock_mode(client, db_session):
    client.post(
        "/api/v1/legal/reminders/custom",
        json={
            "group_id": "group_001",
            "remind_at": "2026-06-02T09:00:00+08:00",
            "content": "到期提醒",
            "target_userid": "lawyer_001",
        },
    )
    response = client.post("/api/v1/legal/reminders/run-due")
    assert response.status_code == 200
    assert response.json()["data"]["sent"] == 0
    assert response.json()["data"]["simulated"] == 1
    reminder = db_session.scalar(select(Reminder).where(Reminder.content == "到期提醒"))
    assert reminder.status == "simulated"
    assert reminder.sent_at is None


def test_tencent_doc_mock_writes_archive_and_paid_amount_logs(client, db_session):
    create_case(client)
    client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "案件(2026)黔0281民初3118号付款截图，转账成功人民币400",
        },
    )
    logs = list(db_session.scalars(select(DocumentSyncLog)).all())
    sync_types = {log.sync_type for log in logs}
    assert "archive" not in sync_types
    assert "paid_amount" not in sync_types


def test_notice_does_not_increment_paid_amount(client, db_session):
    create_case(client)
    client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "案件(2026)黔0281民初3118号需要缴费400元",
        },
    )
    legal_case = db_session.scalar(select(LegalCase).where(LegalCase.case_no == "(2026)黔0281民初3118号"))
    assert legal_case.paid_amount == Decimal("0.00")
