import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.adapters.kdocs import KDocsAdapter
from app.core.config import Settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.group_message import GroupMessage
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.services.business_application_service import BusinessApplicationService
from app.services.legal_text_extraction_service import LegalTextExtractionService
from app.services.repayment_tracking_service import RepaymentTrackingService
from app.utils.datetime_utils import app_timezone, now_tz


AGREEMENT_TEXT = """还款协议
甲方(债权人)：天津新诗商贸有限公司
乙方(债务人)：庞灏，男，汉族
乙方合计欠甲方款项人民币2673.43元。
1. 2026年07月25日：还款668.36元
2. 2026年08月25日：还款668.36元
3. 2026年09月25日：还款668.36元
4. 2026年10月25日：还款668.35元
双方争议均提交玉林仲裁委员会。
日期：2026年07月04日 日期：2026年07月06日
"""


def agreement_result() -> dict:
    return LegalTextExtractionService(Settings(LEGAL_EXTRACTION_MODE="regex")).extract(AGREEMENT_TEXT)


def add_agreement(db_session, tmp_path) -> tuple[LegalEvent, MediaFile, dict]:
    result = agreement_result()
    message = GroupMessage(
        group_id="repayment_group",
        sender_id="FuZhiHang",
        msg_type="pdf",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    path = tmp_path / "庞灏还款协议.pdf"
    path.write_bytes(b"%PDF repayment agreement")
    media = MediaFile(
        group_message_id=message.id,
        group_id=message.group_id,
        msg_id="agreement-msg",
        media_type="pdf",
        original_filename=path.name,
        file_ext=".pdf",
        mime_type="application/pdf",
        md5sum="agreement-md5",
        local_path=str(path),
        download_status="downloaded",
        ocr_status="processed",
        review_status="approved",
        source="test",
        ocr_result_json=json.dumps(result, ensure_ascii=False, default=str),
        review_result_json=json.dumps(result, ensure_ascii=False, default=str),
    )
    db_session.add(media)
    db_session.flush()
    event = LegalEvent(
        group_message_id=message.id,
        event_type="repayment_agreement",
        event_time=now_tz(),
        amount=Decimal("2673.43"),
        attribution_status="not_required",
        business_status="approved",
        approved_by="reviewer",
        approved_at=now_tz(),
        metadata_json=json.dumps(
            {
                "media_file_id": media.id,
                "plaintiff": result["plaintiff"],
                "defendant": result["defendant"],
                **result["metadata"],
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    db_session.add(event)
    db_session.flush()
    media.review_event_id = event.id
    return event, media, result


def test_real_agreement_text_extracts_complete_schedule_without_llm():
    result = agreement_result()
    fields = result["metadata"]["structured_fields"]

    assert result["event_type"] == "repayment_agreement"
    assert result["plaintiff"] == "天津新诗商贸有限公司"
    assert result["defendant"] == "庞灏"
    assert result["amount"] == Decimal("2673.43")
    assert fields["arbitration_institution"] == "玉林仲裁委员会"
    assert fields["agreement_date"] == "2026-07-06"
    assert fields["repayment_plan"]["installment_count"] == 4
    assert fields["repayment_plan"]["installments"][-1] == {
        "sequence": 4,
        "due_date": "2026-10-25",
        "amount": Decimal("668.35"),
    }


def test_repayment_kdocs_merge_preserves_manual_arbitration_fields():
    existing = [
        "天津新诗商贸有限公司",
        "庞灏",
        "原人工附件",
        "齐全",
        "已提交",
        "玉林仲裁委员会",
        "ZC20260720085827S0S",
        None,
        "2026.7.20",
        None,
        "待审查",
        None,
        None,
        None,
        None,
    ]
    incoming = KDocsAdapter()._repayment_values(
        {
            "甲方（债权人）": "天津新诗商贸有限公司",
            "乙方（债务人）": "庞灏",
            "协议文本": "https://kdocs.test/agreement.pdf",
            "提交 履约情况": "已违约",
            "还款方案": "四期还款方案",
            "还款情况": "第1期已逾期",
            "合计还款": "0.00",
        }
    )

    merged = KDocsAdapter._merge_repayment_values(existing, incoming)

    assert merged[2] == "原人工附件"
    assert merged[4] == "已提交,已违约"
    assert merged[6] == "ZC20260720085827S0S"
    assert merged[8] == "2026.7.20"
    assert merged[12:] == ["四期还款方案", "第1期已逾期", "0.00"]


def test_case_independent_agreement_uploads_writes_and_only_creates_future_reminders(db_session, tmp_path):
    event, media, _result = add_agreement(db_session, tmp_path)

    BusinessApplicationService(db_session).apply_event(event.id)

    assert event.business_status == "applied"
    assert media.business_applied_at is not None
    logs = list(db_session.scalars(select(DocumentSyncLog).order_by(DocumentSyncLog.id)).all())
    assert [log.sync_type for log in logs] == ["legal_document_upload", "repayment_agreement"]
    assert all(log.outcome == "applied" for log in logs)
    reminders = list(db_session.scalars(select(Reminder).where(Reminder.source_event_id == event.id)).all())
    assert reminders
    assert all(reminder.case_id is None for reminder in reminders)
    assert all(reminder.remind_at > now_tz() for reminder in reminders)


def test_duplicate_receipt_is_not_double_counted_and_full_payment_completes(db_session, tmp_path):
    agreement, _media, result = add_agreement(db_session, tmp_path)
    BusinessApplicationService(db_session).apply_event(agreement.id)
    tracking = RepaymentTrackingService(db_session)

    for index, (amount, md5sum, sequence) in enumerate(
        [
            ("668.36", "receipt-1", 1),
            ("668.36", "receipt-1", 1),
            ("2005.07", "receipt-final", None),
        ],
        start=1,
    ):
        message = GroupMessage(
            group_id="repayment_group",
            sender_id="FuZhiHang",
            msg_type="image",
            raw_payload_json="{}",
            received_at=datetime(2026, 7, 29, 10, index, tzinfo=app_timezone()),
        )
        db_session.add(message)
        db_session.flush()
        media = MediaFile(
            group_message_id=message.id,
            group_id=message.group_id,
            msg_id=f"receipt-msg-{index}",
            media_type="image",
            md5sum=md5sum,
            download_status="downloaded",
            ocr_status="processed",
            review_status="approved",
            source="test",
        )
        db_session.add(media)
        db_session.flush()
        payment_result = {
            "event_type": "payment_screenshot",
            "plaintiff": result["plaintiff"],
            "defendant": result["defendant"],
            "amount": Decimal(amount),
            "metadata": {
                "repayment_annotation": {"payment_kind": "installment"},
                "structured_fields": {"installment_sequence": sequence} if sequence else {},
            },
        }
        fingerprint = tracking.payment_fingerprint(media, payment_result, agreement.id)
        event = LegalEvent(
            group_message_id=message.id,
            event_type="payment_screenshot",
            event_time=message.received_at,
            amount=Decimal(amount),
            attribution_status="not_required",
            business_status="approved",
            metadata_json=json.dumps(
                {
                    "media_file_id": media.id,
                    "plaintiff": result["plaintiff"],
                    "defendant": result["defendant"],
                    "repayment_agreement_event_id": agreement.id,
                    "repayment_payment_fingerprint": fingerprint,
                    **payment_result["metadata"],
                },
                ensure_ascii=False,
            ),
        )
        db_session.add(event)
        db_session.flush()

    progress = tracking.progress(agreement)

    assert progress["total_paid"] == Decimal("2673.43")
    assert progress["outstanding"] == Decimal("0.00")
    assert progress["status"] == "completed"
    assert len(progress["payment_event_ids"]) == 2
