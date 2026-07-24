from datetime import timedelta
from decimal import Decimal

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder
from app.services.payment_tracking_service import PaymentTrackingService
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
                record_type="payment",
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
    assert "已催促 1 次" in row["tracking_status"]
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
