from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.case_status_history import CaseStatusHistory
from app.models.legal_case import LegalCase
from app.models.reminder import Reminder
from app.models.reminder_send_log import ReminderSendLog
from app.models.system_run_log import SystemRunLog
from app.services.case_lifecycle_service import CaseLifecycleService
from app.utils.datetime_utils import app_timezone


def create_due_reminder(client, content="到期提醒", target_userid="lawyer_001"):
    response = client.post(
        "/api/v1/legal/reminders/custom",
        json={
            "group_id": "group_001",
            "remind_at": "2026-06-02T09:00:00+08:00",
            "content": content,
            "target_userid": target_userid,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def create_case_row(
    db_session,
    case_no,
    due_date,
    status="normal",
    total_amount=Decimal("1000.00"),
    paid_amount=Decimal("0.00"),
):
    legal_case = LegalCase(
        case_no=case_no,
        debtor_name="张三",
        group_id="group_001",
        debtor_wecom_userid="debtor_001",
        lawyer_wecom_userid="lawyer_001",
        due_date=due_date,
        status=status,
        total_amount=total_amount,
        paid_amount=paid_amount,
    )
    db_session.add(legal_case)
    db_session.commit()
    return legal_case


def test_run_due_creates_system_run_log(client, db_session):
    create_due_reminder(client)

    response = client.post("/api/v1/legal/reminders/run-due")

    assert response.status_code == 200
    run_log = db_session.scalar(select(SystemRunLog).where(SystemRunLog.run_type == "reminder_send"))
    assert run_log is not None
    assert run_log.trigger_type == "api"
    assert run_log.status == "success"


def test_run_due_creates_reminder_send_log(client, db_session):
    reminder_id = create_due_reminder(client)

    client.post("/api/v1/legal/reminders/run-due")

    send_log = db_session.scalar(select(ReminderSendLog).where(ReminderSendLog.reminder_id == reminder_id))
    assert send_log is not None
    assert send_log.status == "success"
    assert send_log.send_mode == "mock"


def test_failed_send_creates_failed_reminder_send_log(client, db_session, monkeypatch):
    reminder_id = create_due_reminder(client)

    def fail_send(self, group_id, content, mentioned_userids=None, mentioned_mobiles=None):
        return {"success": False, "mode": "mock", "status_code": None, "response": None, "error": "send failed"}

    monkeypatch.setattr("app.adapters.wecom_message.WeComMessageAdapter.send_text", fail_send)
    client.post("/api/v1/legal/reminders/run-due")

    send_log = db_session.scalar(select(ReminderSendLog).where(ReminderSendLog.reminder_id == reminder_id))
    assert send_log.status == "failed"
    assert send_log.error_message == "send failed"


def test_scan_status_creates_system_run_log(client, db_session):
    create_case_row(db_session, "(2026)黔0281民初8001号", date(2026, 6, 1))

    response = client.post("/api/v1/legal/cases/scan-status")

    assert response.status_code == 200
    run_log = db_session.scalar(select(SystemRunLog).where(SystemRunLog.run_type == "case_status_scan"))
    assert run_log is not None
    assert run_log.trigger_type == "api"
    assert run_log.status == "success"


def test_normal_to_overdue_creates_case_status_history(db_session):
    today = date(2026, 6, 2)
    legal_case = create_case_row(db_session, "(2026)黔0281民初8002号", today - timedelta(days=1))

    CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    history = db_session.scalar(select(CaseStatusHistory).where(CaseStatusHistory.case_id == legal_case.id))
    assert history.old_status == "normal"
    assert history.new_status == "overdue"
    assert history.reason == "overdue_scan"


def test_overdue_to_defaulted_creates_case_status_history(db_session):
    today = date(2026, 6, 5)
    legal_case = create_case_row(db_session, "(2026)黔0281民初8003号", today - timedelta(days=5), status="overdue")
    legal_case.overdue_at = datetime(2026, 6, 2, 9, 0, tzinfo=app_timezone())
    db_session.commit()

    CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    history = db_session.scalar(select(CaseStatusHistory).where(CaseStatusHistory.case_id == legal_case.id))
    assert history.old_status == "overdue"
    assert history.new_status == "defaulted"
    assert history.reason == "default_upgrade"


def test_paid_status_change_creates_case_status_history(db_session):
    today = date(2026, 6, 2)
    legal_case = create_case_row(
        db_session,
        "(2026)黔0281民初8004号",
        today - timedelta(days=1),
        paid_amount=Decimal("1000.00"),
    )

    CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    history = db_session.scalar(select(CaseStatusHistory).where(CaseStatusHistory.case_id == legal_case.id))
    assert history.old_status == "normal"
    assert history.new_status == "paid"
    assert history.reason == "fully_paid"


def test_system_run_logs_api(client):
    create_due_reminder(client)
    client.post("/api/v1/legal/reminders/run-due")

    response = client.get("/api/v1/legal/system-run-logs", params={"run_type": "reminder_send"})

    assert response.status_code == 200
    assert response.json()["data"]["total"] >= 1


def test_case_status_histories_api(client, db_session):
    today = date(2026, 6, 2)
    legal_case = create_case_row(db_session, "(2026)黔0281民初8005号", today - timedelta(days=1))
    CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    response = client.get(f"/api/v1/legal/cases/{legal_case.id}/status-histories")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1


def test_reminder_send_logs_api(client):
    reminder_id = create_due_reminder(client)
    client.post("/api/v1/legal/reminders/run-due")

    response = client.get(f"/api/v1/legal/reminders/{reminder_id}/send-logs")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
