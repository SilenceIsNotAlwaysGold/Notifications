from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.services.api_key_service import ApiKeyService
from app.utils.datetime_utils import now_tz

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_case(db_session, case_no, group_id="group_old", tenant_id=None):
    legal_case = LegalCase(
        case_no=case_no,
        debtor_name="张三",
        tenant_id=tenant_id,
        group_id=group_id,
        debtor_wecom_userid="debtor_old",
        lawyer_wecom_userid="lawyer_old",
        due_date=date(2026, 8, 31),
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("100.00"),
        status="normal",
    )
    db_session.add(legal_case)
    db_session.flush()
    return legal_case


def test_case_patch_updates_binding_pending_reminders_and_unlinked_history(client, db_session):
    legal_case = create_case(db_session, "（2026）黔0281民初8101号")
    reminder = Reminder(
        case_id=legal_case.id,
        group_id="group_old",
        reminder_type="payment_tracking",
        remind_at=now_tz(),
        content="待缴费",
        target_userid="lawyer_old",
        status="pending",
    )
    message = GroupMessage(
        group_id="wr_real_001",
        sender_id="external_user",
        msg_type="file",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add_all([reminder, message])
    db_session.flush()
    event = LegalEvent(group_message_id=message.id, event_type="judgment", metadata_json="{}")
    media = MediaFile(
        group_message_id=message.id,
        group_id="wr_real_001",
        media_type="pdf",
        download_status="downloaded",
        ocr_status="processed",
        source="wecom_archive",
    )
    db_session.add_all([event, media])
    db_session.commit()

    response = client.patch(
        f"/api/v1/legal/cases/{legal_case.id}",
        json={
            "debtor_name": "张三",
            "tenant_id": "tenant_001",
            "group_id": "wr_real_001",
            "debtor_wecom_userid": "debtor_new",
            "lawyer_wecom_userid": "lawyer_new",
            "due_date": "2026-09-15",
            "total_amount": "1200.00",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["case"]["group_id"] == "wr_real_001"
    assert data["updated_pending_reminders"] == 1
    assert data["linked_media_files"] == 0
    assert data["linked_events"] == 0
    assert data["updated_group_messages"] == 0
    assert data["backfill_skipped_reason"] == "历史材料已进入待归属队列，需人工批量确认"

    db_session.expire_all()
    stored_case = db_session.get(LegalCase, legal_case.id)
    stored_reminder = db_session.get(Reminder, reminder.id)
    stored_event = db_session.get(LegalEvent, event.id)
    stored_media = db_session.get(MediaFile, media.id)
    stored_message = db_session.get(GroupMessage, message.id)
    assert stored_case.group_id == "wr_real_001"
    assert stored_case.lawyer_wecom_userid == "lawyer_new"
    assert stored_reminder.group_id == "wr_real_001"
    assert stored_reminder.target_userid == "lawyer_new"
    assert stored_event.case_id is None
    assert stored_media.case_id is None
    assert stored_message.tenant_id is None


def test_case_patch_skips_history_backfill_when_group_has_multiple_cases(client, db_session):
    target_case = create_case(db_session, "（2026）黔0281民初8102号", group_id="wr_shared")
    create_case(db_session, "（2026）黔0281民初8103号", group_id="wr_shared")
    message = GroupMessage(
        group_id="wr_shared",
        sender_id="external_user",
        msg_type="text",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    event = LegalEvent(group_message_id=message.id, event_type="unknown", metadata_json="{}")
    db_session.add(event)
    db_session.commit()

    response = client.patch(
        f"/api/v1/legal/cases/{target_case.id}",
        json={"group_id": "wr_shared", "tenant_id": "tenant_001"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["linked_events"] == 0
    assert "待归属队列" in data["backfill_skipped_reason"]
    db_session.expire_all()
    assert db_session.get(LegalEvent, event.id).case_id is None


def test_message_without_case_number_uses_unique_group_binding(client, db_session):
    legal_case = create_case(db_session, "（2026）黔0281民初8104号", group_id="wr_unique")
    db_session.commit()

    response = client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "wr_unique",
            "sender_id": "external_user",
            "msg_type": "text",
            "content": "请法务今天跟进一下",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["case_id"] == legal_case.id
    event = db_session.scalar(select(LegalEvent).order_by(LegalEvent.id.desc()))
    assert event.case_id == legal_case.id


def test_message_without_case_number_does_not_guess_shared_group_case(client, db_session):
    create_case(db_session, "（2026）黔0281民初8105号", group_id="wr_shared")
    create_case(db_session, "（2026）黔0281民初8106号", group_id="wr_shared")
    db_session.commit()

    response = client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "wr_shared",
            "sender_id": "external_user",
            "msg_type": "text",
            "content": "请法务今天跟进一下",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["case_id"] is None


def test_fullwidth_ocr_case_number_matches_existing_halfwidth_case(client, db_session):
    legal_case = create_case(db_session, "(2026)黔0281民初8109号", group_id="wr_shared")
    create_case(db_session, "(2026)黔0281民初8110号", group_id="wr_shared")
    db_session.commit()

    response = client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "wr_shared",
            "sender_id": "external_user",
            "msg_type": "text",
            "content": "案件（2026）黔0281民初8109号需要缴费400元",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["case_id"] == legal_case.id


def test_case_patch_rejects_total_amount_below_paid_amount(client, db_session):
    legal_case = create_case(db_session, "（2026）黔0281民初8107号")
    legal_case.paid_amount = Decimal("500.00")
    db_session.commit()

    response = client.patch(f"/api/v1/legal/cases/{legal_case.id}", json={"total_amount": "499.99"})

    assert response.status_code == 400
    assert "总金额不能小于已还金额" in response.text


def test_scoped_legal_user_cannot_rebind_case_to_unallowed_group(client, db_session, monkeypatch):
    legal_case = create_case(db_session, "（2026）黔0281民初8108号", group_id="group_allowed")
    db_session.commit()
    key_data = ApiKeyService(db_session).create_api_key(
        name="case-binding-legal",
        role="legal",
        expires_at=None,
        created_by="test",
        allowed_group_ids=["group_allowed"],
        allowed_case_ids=[legal_case.id],
        allowed_tenant_ids=[],
    )
    db_session.commit()
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("RESOURCE_SCOPE_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_KEYS", "admin-test-key")
    get_settings.cache_clear()

    response = client.patch(
        f"/api/v1/legal/cases/{legal_case.id}",
        headers={"X-API-Key": key_data["api_key"]},
        json={"group_id": "group_denied"},
    )

    assert response.status_code == 403
    get_settings.cache_clear()


def test_admin_case_page_exposes_group_binding_editor():
    content = (PROJECT_ROOT / "app/static/admin/admin.js").read_text(encoding="utf-8")

    assert 'data-edit-case="${row.id}"' in content
    assert 'method: "PATCH"' in content
    assert 'id="case-group-options"' in content
    assert "updated_pending_reminders" in content
