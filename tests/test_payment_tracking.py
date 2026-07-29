from datetime import timedelta
from decimal import Decimal
import json

from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder
from app.services.payment_tracking_service import PaymentTrackingService
from app.services.media_file_service import MediaFileService
from app.core.permissions import has_permission
from app.utils.datetime_utils import now_tz


def _case(db_session) -> LegalCase:
    legal_case = LegalCase(
        case_no="(2026)辽0423民初1568号",
        debtor_name="王盛鹏",
        plaintiff_name="杭州圣亿源数码科技有限公司",
        group_id="payment_tracking_group",
        due_date=now_tz().date() + timedelta(days=30),
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        status="normal",
    )
    db_session.add(legal_case)
    db_session.flush()
    return legal_case


def test_payment_tracking_api_matches_customer_ledger_headers(client, db_session):
    legal_case = _case(db_session)
    event = LegalEvent(
        case_id=legal_case.id,
        event_type="payment_notice",
        amount=Decimal("36.00"),
        extracted_text="案件缴费通知，应缴36元",
        attribution_status="confirmed",
        business_status="applied",
    )
    screenshot = MediaFile(
        case_id=legal_case.id,
        group_id=legal_case.group_id,
        media_type="image",
        download_status="downloaded",
        ocr_status="processed",
        local_path="payment/screenshot.jpg",
        source="test",
    )
    db_session.add_all([event, screenshot])
    db_session.flush()
    now = now_tz()
    db_session.add_all(
        [
            Reminder(
                case_id=legal_case.id,
                group_id=legal_case.group_id,
                reminder_type="payment_tracking",
                remind_at=now + timedelta(days=7),
                content="缴费跟踪",
                source_event_id=event.id,
                status="pending",
            ),
            Reminder(
                case_id=legal_case.id,
                group_id=legal_case.group_id,
                reminder_type="payment_tracking",
                remind_at=now,
                content="缴费跟踪",
                source_event_id=event.id,
                status="sent",
                sent_at=now,
            ),
            PaymentRecord(
                case_id=legal_case.id,
                source_media_file_id=screenshot.id,
                applies_to_event_id=event.id,
                record_type="fee_payment",
                amount=Decimal("10.00"),
                status="approved",
                credential_fingerprint="payment-tracking-test",
                created_by="test",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/legal/payment-trackings")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    row = data["items"][0]
    assert row["plaintiff"] == "杭州圣亿源数码科技有限公司"
    assert row["defendant"] == "王盛鹏"
    assert row["case_no"] == "(2026)辽0423民初1568号"
    assert row["payment_info"] == "36.00"
    assert row["payment_status"] == "partial"
    assert "已催促1次" in row["tracking_status"]
    assert row["remaining_payment_time"] == "剩余 7 天"
    assert row["screenshot_url"].endswith(f"/{screenshot.id}/content")


def test_payment_tracking_marks_unpaid_notice_overdue(db_session):
    legal_case = _case(db_session)
    event = LegalEvent(
        case_id=legal_case.id,
        event_type="payment_notice",
        amount=Decimal("36.00"),
        attribution_status="confirmed",
        business_status="applied",
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        Reminder(
            case_id=legal_case.id,
            group_id=legal_case.group_id,
            reminder_type="payment_tracking",
            remind_at=now_tz() - timedelta(days=2),
            content="缴费跟踪",
            source_event_id=event.id,
            status="failed",
        )
    )
    db_session.flush()

    total, rows = PaymentTrackingService(db_session).list_rows(today=now_tz().date())

    assert total == 1
    assert rows[0]["payment_status"] == "overdue"
    assert rows[0]["remaining_payment_time"] == "逾期 2 天"
    assert rows[0]["tracking_status"] == "催促失败 1 次"


def test_standalone_payment_notice_appears_without_case_and_closes_from_confirmation(client, db_session):
    message = GroupMessage(
        group_id="standalone-payment-group",
        sender_id="merchant-sender",
        msg_type="text",
        content="李江胜，案件受理费25元，8月2日前缴费",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    event = LegalEvent(
        group_message_id=message.id,
        event_type="payment_notice",
        amount=Decimal("25.00"),
        extracted_text=message.content,
        metadata_json=json.dumps(
            {"structured_fields": {"defendant": "李江胜", "payment_type": "案件受理费"}},
            ensure_ascii=False,
        ),
        attribution_status="pending",
        business_status="staged",
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        Reminder(
            group_id=message.group_id,
            target_userid=message.sender_id,
            reminder_type="payment_confirmation",
            remind_at=now_tz() + timedelta(minutes=30),
            content="请确认缴费",
            source_event_id=event.id,
            status="pending",
        )
    )
    db_session.commit()

    pending = client.get("/api/v1/legal/payment-trackings")

    assert pending.status_code == 200
    row = pending.json()["data"]["items"][0]
    assert row["case_id"] is None
    assert row["source_group_id"] == message.group_id
    assert row["source_sender_id"] == message.sender_id
    assert row["defendant"] == "李江胜"
    assert row["payment_status"] == "pending"

    metadata = json.loads(event.metadata_json)
    metadata["standalone_payment_confirmation"] = {"message_id": 999, "confirmed_at": now_tz().isoformat()}
    event.metadata_json = json.dumps(metadata, ensure_ascii=False)
    db_session.commit()

    paid = client.get("/api/v1/legal/payment-trackings")
    assert paid.json()["data"]["items"][0]["payment_status"] == "paid"


def test_partial_payment_screenshot_preserves_notice_fields(db_session):
    legal_case = _case(db_session)
    legal_case.paid_amount = Decimal("100.00")
    media = MediaFile(
        case_id=legal_case.id,
        group_id=legal_case.group_id,
        media_type="image",
        local_path="payment/partial.jpg",
        source="test",
    )
    db_session.add(media)
    db_session.flush()

    row = MediaFileService(db_session)._payment_registration_row(
        {"event_type": "payment_screenshot", "amount": Decimal("200.00")},
        legal_case,
        media,
    )

    assert row["日期"] is None
    assert row["缴费信息"] is None
    assert row["支付情况"] == "部分支付"
    assert row["剩余缴费时间"] is None


def test_payment_tracking_permissions_allow_legal_write_and_auditor_read_only():
    read_paths = [
        "/api/v1/legal/payment-trackings",
        "/api/v1/legal/payment-trackings/unassigned-receipts",
        "/api/v1/legal/payment-trackings/daily-summary",
    ]
    assert all(has_permission("legal", "GET", path) for path in read_paths)
    assert all(has_permission("auditor", "GET", path) for path in read_paths)
    assignment = "/api/v1/legal/payment-trackings/12/assign-receipt"
    assert has_permission("legal", "POST", assignment)
    assert not has_permission("auditor", "POST", assignment)
