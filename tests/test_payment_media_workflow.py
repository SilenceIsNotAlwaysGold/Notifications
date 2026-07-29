import json
from decimal import Decimal

from sqlalchemy import select

from app.models.group_message import GroupMessage
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.models.business_outbox import BusinessOutbox
from app.models.wecom_archive_group import WeComArchiveGroup
from app.services.media_file_service import MediaFileService
from app.services.reminder_service import ReminderService
from app.services.outbox_service import OutboxService
from app.services.payment_tracking_service import PaymentTrackingService
from app.utils.datetime_utils import now_tz


GROUP_ID = "payment-media-group"


def _enable_payment_only(db_session) -> None:
    db_session.add(
        WeComArchiveGroup(
            room_id=GROUP_ID,
            status="enabled",
            features_json=json.dumps({"payment_tracking": True, "document_sync": False}),
        )
    )
    db_session.flush()


def _message(db_session, *, msg_type: str, sender_id: str = "fee-sender") -> GroupMessage:
    message = GroupMessage(
        group_id=GROUP_ID,
        sender_id=sender_id,
        msg_type=msg_type,
        content=None,
        raw_payload_json="{}",
        processing_mode="live",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    return message


def test_payment_code_image_is_normalized_to_unpaid_notice():
    result = {"event_type": "payment_screenshot", "event_types": ["payment_screenshot"]}

    MediaFileService._normalize_payment_material(result, "案件受理费 25.00 元 请扫描缴款码支付")

    assert result["event_type"] == "payment_notice"
    assert result["event_types"] == ["payment_notice"]


def test_live_payment_notice_image_creates_30_and_90_minute_followups(db_session):
    _enable_payment_only(db_session)
    message = _message(db_session, msg_type="image")
    media = MediaFile(
        group_message_id=message.id,
        group_id=GROUP_ID,
        media_type="image",
        download_status="downloaded",
        ocr_status="processed",
        review_status="not_required",
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    result = {
        "event_type": "payment_notice",
        "amount": Decimal("25.00"),
        "defendant": "李江胜",
        "case_no": "(2026)桂0702民初5834号",
        "metadata": {"structured_fields": {"payment_type": "案件受理费"}},
    }
    event = LegalEvent(
        group_message_id=message.id,
        event_type="payment_notice",
        amount=Decimal("25.00"),
        attribution_status="not_required",
        business_status="approved",
        metadata_json=json.dumps(result["metadata"], ensure_ascii=False),
    )
    db_session.add(event)
    db_session.flush()

    applied = MediaFileService(db_session)._apply_ocr_business(media, event, result, None)

    reminders = list(db_session.scalars(select(Reminder).order_by(Reminder.remind_at)).all())
    assert applied == {"created_reminders": 2, "cancelled_reminders": 0}
    assert {round((item.remind_at - message.received_at).total_seconds() / 60) for item in reminders} == {30, 90}
    assert {item.target_userid for item in reminders} == {"fee-sender"}


def test_payment_success_image_closes_unique_same_group_notice(db_session):
    _enable_payment_only(db_session)
    notice_message = _message(db_session, msg_type="text")
    notice = LegalEvent(
        group_message_id=notice_message.id,
        event_type="payment_notice",
        amount=Decimal("25.00"),
        extracted_text="李江胜案件受理费25元",
        attribution_status="not_required",
        business_status="staged",
        metadata_json=json.dumps(
            {"structured_fields": {"defendant": "李江胜", "payment_type": "案件受理费"}},
            ensure_ascii=False,
        ),
    )
    db_session.add(notice)
    db_session.flush()
    ReminderService(db_session).create_standalone_payment_confirmation_followups(
        notice,
        notice_message,
        {
            "amount": Decimal("25.00"),
            "defendant": "李江胜",
            "metadata": {"structured_fields": {"payment_type": "案件受理费"}},
        },
    )

    receipt_message = _message(db_session, msg_type="image", sender_id="payer")
    media = MediaFile(
        group_message_id=receipt_message.id,
        group_id=GROUP_ID,
        media_type="image",
        download_status="downloaded",
        ocr_status="processed",
        review_status="not_required",
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    result = {
        "event_type": "payment_screenshot",
        "amount": Decimal("25.00"),
        "defendant": "李江胜",
        "raw_text": "支付成功 李江胜 案件受理费 25.00元",
        "metadata": {},
    }
    from app.services.payment_tracking_service import PaymentTrackingService

    assert PaymentTrackingService(db_session).link_media_receipt_result(media, result).id == notice.id
    receipt = LegalEvent(
        group_message_id=receipt_message.id,
        event_type="payment_screenshot",
        amount=Decimal("25.00"),
        attribution_status="not_required",
        business_status="approved",
        metadata_json=json.dumps(result["metadata"], ensure_ascii=False),
    )
    db_session.add(receipt)
    db_session.flush()

    applied = MediaFileService(db_session)._apply_ocr_business(media, receipt, result, None)

    reminders = list(db_session.scalars(select(Reminder)).all())
    assert applied == {"created_reminders": 0, "cancelled_reminders": 2}
    assert {item.status for item in reminders} == {"cancelled"}
    assert json.loads(notice.metadata_json)["standalone_payment_confirmation"]["media_file_id"] == media.id


def test_ambiguous_payment_receipt_stays_unmatched(db_session):
    for defendant in ("张三", "李四"):
        message = _message(db_session, msg_type="text", sender_id=defendant)
        db_session.add(
            LegalEvent(
                group_message_id=message.id,
                event_type="payment_notice",
                amount=Decimal("25.00"),
                extracted_text=f"{defendant}案件受理费25元",
                attribution_status="not_required",
                business_status="staged",
                metadata_json="{}",
            )
        )
    receipt_message = _message(db_session, msg_type="image", sender_id="payer")
    media = MediaFile(group_message_id=receipt_message.id, group_id=GROUP_ID, media_type="image", source="test")
    db_session.add(media)
    db_session.flush()
    result = {"event_type": "payment_screenshot", "amount": Decimal("25.00"), "raw_text": "支付成功25元", "metadata": {}}

    from app.services.payment_tracking_service import PaymentTrackingService

    assert PaymentTrackingService(db_session).link_media_receipt_result(media, result) is None
    assert result["metadata"]["unmatched_payment_receipt"] is True
    assert len(result["metadata"]["payment_notice_candidate_ids"]) == 2


def test_receipt_without_party_case_or_fee_evidence_does_not_claim_single_notice(db_session):
    message = _message(db_session, msg_type="text")
    notice = LegalEvent(
        group_message_id=message.id,
        event_type="payment_notice",
        amount=Decimal("400.00"),
        extracted_text="王成公告费400元",
        attribution_status="not_required",
        business_status="staged",
        metadata_json=json.dumps({"structured_fields": {"defendant": "王成", "payment_type": "公告费"}}),
    )
    db_session.add(notice)
    receipt_message = _message(db_session, msg_type="image", sender_id="payer")
    media = MediaFile(group_message_id=receipt_message.id, group_id=GROUP_ID, media_type="image", source="test")
    db_session.add(media)
    db_session.flush()
    result = {"event_type": "payment_screenshot", "raw_text": "支付成功", "metadata": {}}

    assert PaymentTrackingService(db_session).link_media_receipt_result(media, result) is None
    assert result["metadata"]["payment_notice_candidate_ids"] == [notice.id]


def test_manual_same_group_media_assignment_cancels_followups_through_outbox(db_session):
    _enable_payment_only(db_session)
    notice_message = _message(db_session, msg_type="text")
    notice = LegalEvent(
        group_message_id=notice_message.id,
        event_type="payment_notice",
        amount=Decimal("25.00"),
        extracted_text="李江胜案件受理费25元",
        attribution_status="not_required",
        business_status="staged",
        metadata_json=json.dumps({"structured_fields": {"defendant": "李江胜", "payment_type": "案件受理费"}}),
    )
    db_session.add(notice)
    db_session.flush()
    ReminderService(db_session).create_standalone_payment_confirmation_followups(
        notice,
        notice_message,
        {"amount": Decimal("25.00"), "defendant": "李江胜", "metadata": {"structured_fields": {"payment_type": "案件受理费"}}},
    )
    receipt_message = _message(db_session, msg_type="image", sender_id="payer")
    result = {
        "event_type": "payment_screenshot",
        "amount": "25.00",
        "raw_text": "支付成功25元",
        "metadata": {"unmatched_payment_receipt": True, "payment_notice_candidate_ids": [notice.id]},
    }
    media = MediaFile(
        group_message_id=receipt_message.id,
        group_id=GROUP_ID,
        media_type="image",
        local_path="/tmp/payment-receipt.png",
        ocr_status="processed",
        review_status="pending",
        ocr_result_json=json.dumps(result, ensure_ascii=False),
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    receipt = LegalEvent(
        group_message_id=receipt_message.id,
        event_type="payment_screenshot",
        amount=Decimal("25.00"),
        attribution_status="pending",
        business_status="staged",
        metadata_json=json.dumps({"media_file_id": media.id}),
    )
    db_session.add(receipt)
    db_session.flush()
    media.review_event_id = receipt.id
    db_session.flush()

    total, unmatched = PaymentTrackingService(db_session).list_unmatched_media_receipts()
    assert total == 1
    assert unmatched[0]["candidate_event_ids"] == [notice.id]

    PaymentTrackingService(db_session).assign_media_receipt(notice, media, "admin:test")
    task = db_session.scalar(select(BusinessOutbox).where(BusinessOutbox.aggregate_id == receipt.id))
    assert task is not None

    assert OutboxService(db_session).process_pending() == {"processed": 1, "completed": 1, "failed": 0}
    assert {item.status for item in db_session.scalars(select(Reminder)).all()} == {"cancelled"}
    assert receipt.business_status == "applied"
    assert media.business_applied_at is not None
