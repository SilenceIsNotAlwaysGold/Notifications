import json
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
        "payment_kind": "installment",
        "raw_text": "原告：甲公司 + 被告：张三 + 第2期还款 + 金额：1,200.50元",
    }


def test_parse_compact_repayment_annotations_from_real_messages():
    samples = [
        ("深圳市福田区展盛数码商行(个体工商户) 张俊杰第二期还款959.22元", "深圳市福田区展盛数码商行(个体工商户)", "张俊杰", 2, "959.22"),
        ("中山市优趣儿童用品有限公司石航天第一期还款1000元", "中山市优趣儿童用品有限公司", "石航天", 1, "1000.00"),
        ("广州市番禺区钟村长希炖品店 张新宇已还款第一期821.46元", "广州市番禺区钟村长希炖品店", "张新宇", 1, "821.46"),
        ("抚州西鹏商贸有限公司郑礼灿第三期还款821元", "抚州西鹏商贸有限公司", "郑礼灿", 3, "821.00"),
    ]

    for text, plaintiff, defendant, sequence, amount in samples:
        result = parse_repayment_annotation(text)
        assert result is not None
        assert result["plaintiff"] == plaintiff
        assert result["defendant"] == defendant
        assert result["installment_sequence"] == sequence
        assert result["amount"] == Decimal(amount)


def test_parse_real_payment_variants_without_fixed_plus_format():
    samples = [
        ("可可店+黄建勇+一次性结清+2700", "可可店", "黄建勇", None, "2700.00", "full_settlement"),
        ("南城县蹦蹦虎-彭世雄 第一期还款 350元", "南城县蹦蹦虎", "彭世雄", 1, "350.00", "installment"),
        ("湖北旺利数码科技有限公司-王硕-第二期付款800", "湖北旺利数码科技有限公司", "王硕", 2, "800.00", "installment"),
        ("玉龙蜜桔科技、卢家红 4100一次性结清", "玉龙蜜桔科技", "卢家红", None, "4100.00", "full_settlement"),
        (
            "普宁市洪阳欧气满满电子产品经营部(个体工商户)，被告罗绒绒，支付1269.75元，案件已完结。",
            "普宁市洪阳欧气满满电子产品经营部(个体工商户)",
            "罗绒绒",
            None,
            "1269.75",
            "completed",
        ),
    ]

    for text, plaintiff, defendant, sequence, amount, payment_kind in samples:
        result = parse_repayment_annotation(text)
        assert result is not None
        assert result["plaintiff"] == plaintiff
        assert result["defendant"] == defendant
        assert result["installment_sequence"] == sequence
        assert result["amount"] == Decimal(amount)
        assert result["payment_kind"] == payment_kind


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

    def fake_process(self, media_file_id, trigger_type="system", operator=None, **kwargs):
        captured.update(media_file_id=media_file_id, trigger_type=trigger_type, operator=operator, **kwargs)
        return {"event_id": 9}

    monkeypatch.setattr(MediaFileService, "process_ocr", fake_process)
    annotation = parse_repayment_annotation(annotation_message.content)

    result = MediaFileService(db_session).reanalyze_repayment_screenshot_annotation(annotation_message, annotation)

    assert result["linked_media_file_id"] == media.id
    assert captured == {
        "media_file_id": media.id,
        "trigger_type": "repayment_annotation",
        "operator": "system:repayment-annotation",
        "force_reprocess": True,
        "stage_only": True,
        "preferred_context_message_id": annotation_message.id,
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


def test_reanalysis_plan_pairs_text_before_image_and_uses_each_image_once(db_session):
    base = now_tz()
    first_text = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="text",
        content="甲公司+张三+一次性结清+500元",
        raw_payload_json="{}",
        received_at=base,
    )
    image_message = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=base + timedelta(seconds=1),
    )
    second_text = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="text",
        content="乙公司+李四+第2期还款+800元",
        raw_payload_json="{}",
        received_at=base + timedelta(seconds=2),
    )
    db_session.add_all([first_text, image_message, second_text])
    db_session.flush()
    media = MediaFile(
        group_message_id=image_message.id,
        group_id="repayment_group",
        media_type="image",
        download_status="downloaded",
        ocr_status="processed",
        review_status="pending",
        ocr_result_json='{"metadata": {}}',
        source="mock",
    )
    db_session.add(media)
    db_session.flush()

    plan = MediaFileService(db_session).repayment_reanalysis_plan(limit=20)

    assert len(plan) == 1
    assert plan[0]["message_id"] == first_text.id
    assert plan[0]["media_file_id"] == media.id
    assert plan[0]["distance_seconds"] == 1.0


def test_reanalysis_plan_prefers_near_caption_over_older_unrelated_caption(db_session):
    base = now_tz()
    stale = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="text",
        content="甲公司+张三+第1期还款+449.63元",
        raw_payload_json="{}",
        received_at=base,
    )
    image_message = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=base + timedelta(minutes=6),
    )
    matching = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="text",
        content="乙公司+李四+第2期还款+1650.62元",
        raw_payload_json="{}",
        received_at=base + timedelta(minutes=6, milliseconds=30),
    )
    db_session.add_all([stale, image_message, matching])
    db_session.flush()
    media = MediaFile(
        group_message_id=image_message.id,
        group_id="repayment_group",
        media_type="image",
        download_status="downloaded",
        ocr_status="processed",
        review_status="pending",
        ocr_result_json='{"metadata": {}}',
        source="mock",
    )
    db_session.add(media)
    db_session.flush()

    plan = MediaFileService(db_session).repayment_reanalysis_plan(limit=20)

    assert len(plan) == 1
    assert plan[0]["message_id"] == matching.id
    assert plan[0]["annotation"]["amount"] == "1650.62"
    assert plan[0]["distance_seconds"] == 0.03


def test_reanalysis_plan_skips_already_staged_material(db_session):
    base = now_tz()
    caption = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="text",
        content="甲公司+张三+第1期还款+500元",
        raw_payload_json="{}",
        received_at=base,
    )
    image_message = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=base + timedelta(seconds=1),
    )
    db_session.add_all([caption, image_message])
    db_session.flush()
    db_session.add(
        MediaFile(
            group_message_id=image_message.id,
            group_id="repayment_group",
            media_type="image",
            download_status="downloaded",
            ocr_status="processed",
            review_status="pending",
            ocr_result_json='{"metadata": {"stage_only_reanalysis": true}}',
            source="mock",
        )
    )
    db_session.flush()

    assert MediaFileService(db_session).repayment_reanalysis_plan(limit=20) == []


def test_reanalysis_plan_does_not_reuse_caption_across_batches(db_session):
    base = now_tz()
    caption = GroupMessage(
        group_id="repayment_group",
        sender_id="operator",
        msg_type="text",
        content="甲公司+张三+第1期还款+500元",
        raw_payload_json="{}",
        received_at=base,
    )
    first_image = GroupMessage(group_id="repayment_group", sender_id="u1", msg_type="image", raw_payload_json="{}", received_at=base + timedelta(seconds=1))
    second_image = GroupMessage(group_id="repayment_group", sender_id="u1", msg_type="image", raw_payload_json="{}", received_at=base + timedelta(seconds=2))
    db_session.add_all([caption, first_image, second_image])
    db_session.flush()
    db_session.add_all(
        [
            MediaFile(
                group_message_id=first_image.id,
                group_id="repayment_group",
                media_type="image",
                download_status="downloaded",
                ocr_status="processed",
                review_status="pending",
                ocr_result_json=json.dumps(
                    {
                        "metadata": {"stage_only_reanalysis": True},
                        "context_messages": [{"message_id": caption.id, "msg_type": "text", "content": caption.content}],
                    }
                ),
                source="mock",
            ),
            MediaFile(
                group_message_id=second_image.id,
                group_id="repayment_group",
                media_type="image",
                download_status="downloaded",
                ocr_status="processed",
                review_status="pending",
                ocr_result_json='{"metadata": {}}',
                source="mock",
            ),
        ]
    )
    db_session.flush()

    assert MediaFileService(db_session).repayment_reanalysis_plan(limit=20) == []


def test_reanalysis_execution_is_force_reprocessed_and_staged(db_session, monkeypatch):
    service = MediaFileService(db_session)
    monkeypatch.setattr(service, "repayment_reanalysis_plan", lambda limit, auth_context=None: [{"message_id": 1, "media_file_id": 2}])
    captured = {}

    def fake_process(media_file_id, trigger_type, operator, **kwargs):
        captured.update(media_file_id=media_file_id, trigger_type=trigger_type, operator=operator, **kwargs)
        return {"event_id": 3, "event_type": "payment_screenshot"}

    monkeypatch.setattr(service, "process_ocr", fake_process)

    result = service.reanalyze_repayment_annotations(limit=10, operator="reviewer")

    assert result["stage_only"] is True
    assert result["processed"] == 1
    assert captured == {
        "media_file_id": 2,
        "trigger_type": "repayment_annotation_backfill",
        "operator": "reviewer",
        "force_reprocess": True,
        "stage_only": True,
        "preferred_context_message_id": 1,
    }
