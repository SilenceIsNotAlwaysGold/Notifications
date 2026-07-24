from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.reminder import Reminder
from app.models.reminder_rule import ReminderRule
from app.services.reminder_rule_service import ReminderRuleService
from app.services.reminder_service import ReminderService
from app.utils.datetime_utils import app_timezone


def _case(db_session) -> LegalCase:
    legal_case = LegalCase(
        case_no="(2026)黔0281民初8801号",
        debtor_name="张三",
        group_id="group_rules",
        debtor_wecom_userid="debtor_001",
        lawyer_wecom_userid="lawyer_001",
        due_date=date(2026, 8, 20),
        status="normal",
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("100.00"),
    )
    db_session.add(legal_case)
    db_session.commit()
    return legal_case


def test_default_rules_have_all_standard_tiers(client):
    response = client.get("/api/v1/legal/reminder-rules")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 13
    assert {item["offset_days"] for item in items if item["rule_type"] == "repayment"} == {0, 1, 3, 7}
    assert {item["offset_days"] for item in items if item["rule_type"] == "default_upgrade"} == {1, 3, 7}
    assert {item["offset_days"] for item in items if item["rule_type"] == "payment_tracking"} == {3, 5, 7}
    assert {item["offset_days"] for item in items if item["rule_type"] == "court_mode_confirmation"} == {5}
    assert {item["offset_days"] for item in items if item["rule_type"] == "court_reminder"} == {1, 3}
    assert all(item["send_time"] == "09:00" for item in items)


def test_rule_engine_creates_all_repayment_and_default_tiers_once(db_session):
    legal_case = _case(db_session)
    service = ReminderService(db_session)

    for offset in (7, 3, 1, 0):
        created = service.create_repayment_rules_for_date(legal_case.id, legal_case.due_date - timedelta(days=offset))
        assert len(created) == 1
        assert created[0].remind_at.hour == 9
    assert service.create_repayment_rules_for_date(legal_case.id, legal_case.due_date - timedelta(days=3)) == []

    legal_case.status = "overdue"
    legal_case.overdue_at = datetime(2026, 8, 21, 9, 0, tzinfo=app_timezone())
    db_session.flush()
    for offset in (1, 3, 7):
        created = service.create_default_rules_for_date(legal_case.id, legal_case.overdue_at.date() + timedelta(days=offset))
        assert len(created) == 1

    reminders = list(db_session.scalars(select(Reminder).where(Reminder.case_id == legal_case.id)).all())
    assert len(reminders) == 7
    assert len({item.dedupe_key for item in reminders}) == 7


def test_invalid_template_variable_is_rejected(client):
    response = client.post(
        "/api/v1/legal/reminder-rules",
        json={
            "name": "非法模板",
            "rule_type": "repayment",
            "offset_days": 2,
            "template": "案件 {case_no} 密钥 {secret}",
        },
    )

    assert response.status_code == 400
    assert "不支持的变量" in response.json()["message"]


def test_court_notice_creates_confirmation_and_hearing_reminders(db_session):
    legal_case = _case(db_session)
    event = LegalEvent(
        case_id=legal_case.id,
        event_type="court_notice",
        event_time=datetime(2026, 8, 30, 9, 30, tzinfo=app_timezone()),
        attribution_status="confirmed",
        business_status="approved",
    )
    db_session.add(event)
    db_session.flush()

    created = ReminderService(db_session).create_court_reminders(
        legal_case.id, event.event_time, source_event_id=event.id
    )

    assert len(created) == 3
    assert {item.remind_at.date() for item in created} == {
        date(2026, 8, 25), date(2026, 8, 27), date(2026, 8, 29)
    }
    assert {item.reminder_type for item in created} == {"court_mode_confirmation", "court_reminder"}


def test_installment_plan_creates_idempotent_reminders(db_session):
    legal_case = _case(db_session)
    event = LegalEvent(
        case_id=legal_case.id,
        event_type="repayment_agreement",
        attribution_status="confirmed",
        business_status="approved",
    )
    db_session.add(event)
    db_session.flush()
    installments = [
        {"sequence": 1, "due_date": "2026-09-01", "amount": 500},
        {"sequence": 2, "due_date": "2026-10-01", "amount": 500},
    ]
    service = ReminderService(db_session)

    first = service.create_installment_reminders(legal_case.id, installments, source_event_id=event.id)
    second = service.create_installment_reminders(legal_case.id, installments, source_event_id=event.id)

    assert len(first) == 6
    assert second == []
    assert {item.reminder_type for item in first} == {"installment_repayment"}


def test_rule_change_rebuilds_pending_and_disable_cancels(db_session, client):
    legal_case = _case(db_session)
    event = LegalEvent(
        case_id=legal_case.id,
        group_message_id=None,
        event_type="payment_notice",
        event_time=datetime(2026, 7, 20, 8, 0, tzinfo=app_timezone()),
        amount=Decimal("400.00"),
        metadata_json="{}",
    )
    db_session.add(event)
    db_session.commit()
    reminders = ReminderService(db_session).create_payment_tracking(
        legal_case.id,
        date(2026, 7, 20),
        source_event_id=event.id,
        payment_amount=event.amount,
    )
    db_session.commit()
    target = reminders[0]

    response = client.patch(
        f"/api/v1/legal/reminder-rules/{target.rule_id}",
        json={"template": "案件 {case_no} 缴费金额 {payment_amount}，请立即核对"},
    )
    assert response.status_code == 200
    db_session.expire_all()
    refreshed = db_session.get(Reminder, target.id)
    assert "请立即核对" in refreshed.content

    disabled = client.patch(f"/api/v1/legal/reminder-rules/{target.rule_id}", json={"enabled": False})
    assert disabled.status_code == 200
    db_session.expire_all()
    assert db_session.get(Reminder, target.id).status == "cancelled"


def test_custom_reminder_can_be_edited_then_cancelled(client, db_session):
    created = client.post(
        "/api/v1/legal/reminders/custom",
        json={
            "group_id": "group_custom",
            "remind_at": "2026-08-01T09:00:00+08:00",
            "content": "初始内容",
        },
    )
    reminder_id = created.json()["data"]["id"]

    updated = client.patch(
        f"/api/v1/legal/reminders/{reminder_id}",
        json={"remind_at": "2026-08-02T10:30:00+08:00", "content": "修正后的内容"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["content"] == "修正后的内容"

    cancelled = client.post(
        f"/api/v1/legal/reminders/{reminder_id}/cancel",
        json={"reason": "事项已处理"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert "事项已处理" in cancelled.json()["data"]["cancel_reason"]

    rejected_edit = client.patch(f"/api/v1/legal/reminders/{reminder_id}", json={"content": "再次修改"})
    assert rejected_edit.status_code == 400


def test_mock_send_is_recorded_as_simulated(client, db_session):
    created = client.post(
        "/api/v1/legal/reminders/custom",
        json={
            "group_id": "group_custom",
            "remind_at": "2026-06-01T09:00:00+08:00",
            "content": "模拟提醒",
        },
    )
    reminder_id = created.json()["data"]["id"]

    response = client.post("/api/v1/legal/reminders/run-due")

    assert response.status_code == 200
    assert response.json()["data"]["simulated"] == 1
    db_session.expire_all()
    reminder = db_session.get(Reminder, reminder_id)
    assert reminder.status == "simulated"
    assert reminder.sent_at is None
