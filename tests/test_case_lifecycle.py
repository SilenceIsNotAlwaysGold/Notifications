from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.reminder import Reminder
from app.services.case_lifecycle_service import CaseLifecycleService
from app.utils.datetime_utils import app_timezone


def create_case_row(
    db_session,
    case_no,
    due_date,
    status="normal",
    total_amount=Decimal("1000.00"),
    paid_amount=Decimal("0.00"),
    debtor_wecom_userid="debtor_001",
    lawyer_wecom_userid="lawyer_001",
):
    legal_case = LegalCase(
        case_no=case_no,
        debtor_name="张三",
        group_id="group_001",
        debtor_wecom_userid=debtor_wecom_userid,
        lawyer_wecom_userid=lawyer_wecom_userid,
        due_date=due_date,
        status=status,
        total_amount=total_amount,
        paid_amount=paid_amount,
    )
    db_session.add(legal_case)
    db_session.commit()
    return legal_case


def test_due_before_n_days_creates_repayment_reminder(db_session):
    today = date(2026, 6, 2)
    legal_case = create_case_row(db_session, "(2026)黔0281民初7001号", today + timedelta(days=3))

    result = CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    reminder = db_session.scalar(select(Reminder).where(Reminder.case_id == legal_case.id))
    assert result["created_repayment_reminders"] == 1
    assert reminder.reminder_type == "repayment_before_due"
    assert reminder.target_userid == "debtor_001"
    assert legal_case.repayment_reminder_created_at is not None


def test_repayment_reminder_is_idempotent(db_session):
    today = date(2026, 6, 2)
    create_case_row(db_session, "(2026)黔0281民初7002号", today + timedelta(days=3))

    service = CaseLifecycleService(db_session)
    first = service.scan_cases(today=today)
    second = service.scan_cases(today=today)
    db_session.commit()

    reminders = list(db_session.scalars(select(Reminder).where(Reminder.reminder_type == "repayment_before_due")).all())
    assert first["created_repayment_reminders"] == 1
    assert second["created_repayment_reminders"] == 0
    assert len(reminders) == 1


def test_past_due_unpaid_normal_case_marks_overdue(db_session):
    today = date(2026, 6, 2)
    legal_case = create_case_row(db_session, "(2026)黔0281民初7003号", today - timedelta(days=1))

    result = CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    assert result["marked_overdue"] == 1
    assert legal_case.status == "overdue"
    assert legal_case.overdue_at is not None


def test_overdue_status_sync_log_written(db_session):
    today = date(2026, 6, 2)
    create_case_row(db_session, "(2026)黔0281民初7004号", today - timedelta(days=1))

    CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "status"))
    assert log is not None
    assert log.status == "success"
    assert log.external_sheet_name == "致和法务/案件台账"


def test_overdue_after_three_days_marks_defaulted(db_session):
    today = date(2026, 6, 5)
    legal_case = create_case_row(db_session, "(2026)黔0281民初7005号", today - timedelta(days=5), status="overdue")
    legal_case.overdue_at = datetime(2026, 6, 2, 9, 0, tzinfo=app_timezone())
    db_session.commit()

    result = CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    assert result["marked_defaulted"] == 1
    assert legal_case.status == "defaulted"
    assert legal_case.defaulted_at is not None


def test_defaulted_creates_default_upgrade_reminder(db_session):
    today = date(2026, 6, 5)
    legal_case = create_case_row(db_session, "(2026)黔0281民初7006号", today - timedelta(days=5), status="overdue")
    legal_case.overdue_at = datetime(2026, 6, 2, 9, 0, tzinfo=app_timezone())
    db_session.commit()

    result = CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    reminder = db_session.scalar(select(Reminder).where(Reminder.reminder_type == "default_upgrade"))
    assert result["created_default_upgrade_reminders"] == 1
    assert reminder.case_id == legal_case.id
    assert "强制执行 / 仲裁" in reminder.content


def test_default_upgrade_reminder_targets_lawyer(db_session):
    today = date(2026, 6, 5)
    create_case = create_case_row(db_session, "(2026)黔0281民初7007号", today - timedelta(days=5), status="overdue")
    create_case.overdue_at = datetime(2026, 6, 2, 9, 0, tzinfo=app_timezone())
    db_session.commit()

    CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    reminder = db_session.scalar(select(Reminder).where(Reminder.reminder_type == "default_upgrade"))
    assert reminder.target_userid == "lawyer_001"


def test_fully_paid_case_marks_paid(db_session):
    today = date(2026, 6, 2)
    legal_case = create_case_row(
        db_session,
        "(2026)黔0281民初7008号",
        today - timedelta(days=1),
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("1000.00"),
    )

    result = CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    assert result["marked_paid"] == 1
    assert legal_case.status == "paid"
    assert legal_case.paid_at is not None


def test_paid_case_does_not_enter_overdue_or_defaulted(db_session):
    today = date(2026, 6, 5)
    legal_case = create_case_row(
        db_session,
        "(2026)黔0281民初7009号",
        today - timedelta(days=5),
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("1000.00"),
    )

    result = CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    assert result["marked_paid"] == 1
    assert result["marked_overdue"] == 0
    assert result["marked_defaulted"] == 0
    assert legal_case.status == "paid"


def test_closed_case_is_not_scanned(db_session):
    today = date(2026, 6, 2)
    legal_case = create_case_row(db_session, "(2026)黔0281民初7010号", today - timedelta(days=5), status="closed")

    result = CaseLifecycleService(db_session).scan_cases(today=today)
    db_session.commit()

    assert result["checked"] == 0
    assert legal_case.status == "closed"


def test_scan_status_api_works(client):
    response = client.post(
        "/api/v1/legal/cases",
        json={
            "case_no": "(2026)黔0281民初7011号",
            "debtor_name": "张三",
            "group_id": "group_001",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )
    assert response.status_code == 200

    scan_response = client.post("/api/v1/legal/cases/scan-status")

    assert scan_response.status_code == 200
    assert scan_response.json()["code"] == 0
    assert "checked" in scan_response.json()["data"]


def test_get_case_detail_api_includes_lifecycle_fields(client, db_session):
    legal_case = create_case_row(db_session, "(2026)黔0281民初7012号", date(2026, 6, 30))

    response = client.get(f"/api/v1/legal/cases/{legal_case.id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == legal_case.id
    assert "overdue_at" in data
