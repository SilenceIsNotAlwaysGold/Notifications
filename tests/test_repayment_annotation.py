from datetime import date, timedelta
from decimal import Decimal

from app.core.config import Settings
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.media_file import MediaFile
from app.schemas.legal import MockMessageCreate
from app.services.case_service import CaseService
from app.services.legal_text_extraction_service import LegalTextExtractionService
from app.services.media_file_service import MediaFileService
from app.services.message_service import MessageService
from app.utils.datetime_utils import now_tz
from app.utils.repayment_annotation import parse_repayment_annotation


def test_parse_labeled_repayment_annotation():
    result = parse_repayment_annotation("原告：甲公司 + 被告：张三 + 第2期还款 + 金额：1,200.50元")

    assert result == {
        "plaintiff": "甲公司",
        "defendant": "张三",
        "installment_sequence": 2,
        "amount": Decimal("1200.50"),
        "raw_text": "原告：甲公司 + 被告：张三 + 第2期还款 + 金额：1,200.50元",
    }


def test_annotation_after_image_overrides_ocr_payment_fields():
    service = LegalTextExtractionService(Settings(LEGAL_EXTRACTION_MODE="regex"))
    context = [
        {
            "message_id": 22,
            "sender_id": "operator",
            "msg_type": "text",
            "content": "甲公司+张三+第3期还款+800元",
            "received_at": now_tz().isoformat(),
            "position": "after",
        }
    ]

    result = service.extract("微信支付交易成功", context_messages=context)

    assert result["event_type"] == "payment_screenshot"
    assert result["plaintiff"] == "甲公司"
    assert result["defendant"] == "张三"
    assert result["amount"] == Decimal("800.00")
    assert result["metadata"]["structured_fields"]["installment_sequence"] == 3
    assert result["metadata"]["repayment_annotation"]["message_id"] == 22


def test_payment_screenshot_waits_for_annotation_before_auto_processing():
    assert MediaFileService._result_requires_review(
        {"event_type": "payment_screenshot", "requires_review": False, "metadata": {}}
    )
    assert not MediaFileService._result_requires_review(
        {
            "event_type": "payment_screenshot",
            "requires_review": False,
            "metadata": {"repayment_annotation": {"message_id": 22}},
        }
    )


def test_party_names_resolve_one_case_in_multi_case_group(db_session):
    db_session.add_all(
        [
            LegalCase(
                case_no="(2026)黔0281民初9101号",
                plaintiff_name="甲公司",
                debtor_name="张三",
                group_id="multi_group",
                due_date=date(2026, 9, 1),
                total_amount=Decimal("1000"),
                paid_amount=Decimal("0"),
                status="normal",
            ),
            LegalCase(
                case_no="(2026)黔0281民初9102号",
                plaintiff_name="乙公司",
                debtor_name="李四",
                group_id="multi_group",
                due_date=date(2026, 9, 1),
                total_amount=Decimal("1000"),
                paid_amount=Decimal("0"),
                status="normal",
            ),
        ]
    )
    db_session.flush()

    matched = CaseService(db_session).find_case_for_extracted(
        None,
        "multi_group",
        plaintiff="乙公司",
        defendant="李四",
    )

    assert matched is not None
    assert matched.case_no == "(2026)黔0281民初9102号"


def test_annotation_reanalyzes_nearest_recent_image_without_case_number(db_session, monkeypatch):
    image_message = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=now_tz() - timedelta(minutes=2),
    )
    annotation_message = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="text",
        content="甲公司+张三+第1期还款+500元",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add_all([image_message, annotation_message])
    db_session.flush()
    media = MediaFile(
        group_message_id=image_message.id,
        group_id="repayment_group",
        media_type="image",
        download_status="downloaded",
        ocr_status="processed",
        review_status="pending",
        ocr_result_json='{"context_messages": []}',
        source="mock",
    )
    db_session.add(media)
    db_session.flush()
    captured = {}

    def fake_process(self, media_file_id, trigger_type="system", operator=None):
        captured.update(media_file_id=media_file_id, trigger_type=trigger_type, operator=operator)
        return {"event_id": 9}

    monkeypatch.setattr(MediaFileService, "process_ocr", fake_process)
    annotation = parse_repayment_annotation(annotation_message.content)

    result = MediaFileService(db_session).reanalyze_repayment_screenshot_annotation(annotation_message, annotation)

    assert result["linked_media_file_id"] == media.id
    assert captured == {
        "media_file_id": media.id,
        "trigger_type": "repayment_annotation",
        "operator": "system:repayment-annotation",
    }


def test_linked_annotation_does_not_create_duplicate_text_event(db_session, monkeypatch):
    monkeypatch.setattr(
        MediaFileService,
        "reanalyze_repayment_screenshot_annotation",
        lambda self, message, annotation: {"event_id": 77, "linked_media_file_id": 12},
    )

    result = MessageService(db_session).handle_incoming_message(
        MockMessageCreate(
            group_id="repayment_group",
            sender_id="operator",
            msg_type="text",
            content="甲公司+张三+第4期还款+900元",
        )
    )

    assert result["event_ids"] == [77]
    assert result["linked_media_file_id"] == 12
    assert result["extracted"]["event_types"] == ["payment_screenshot"]
