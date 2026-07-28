import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.business_outbox import BusinessOutbox
from app.models.attribution_item import AttributionItem
from app.models.document_sync_log import DocumentSyncLog
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder
from app.models.wecom_archive_group import WeComArchiveGroup
from app.services.business_application_service import BusinessApplicationService
from app.services.attribution_service import AttributionService
from app.services.media_file_service import MediaFileService
from app.services.outbox_service import OutboxService
from app.utils.datetime_utils import now_tz


def _case(client, case_no="（2026）黔0281民初9001号", group_id="workflow_group", total="1000.00"):
    response = client.post(
        "/api/v1/legal/cases",
        json={
            "case_no": case_no,
            "debtor_name": "测试被告",
            "group_id": group_id,
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "total_amount": total,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def test_confirmed_case_event_stays_staged_until_human_approval(client, db_session):
    case_id = _case(client)
    response = client.post(
        "/api/v1/legal/messages/mock",
        json={"group_id": "workflow_group", "sender_id": "u1", "msg_type": "text", "content": "案件（2026）黔0281民初9001号需要缴费100元"},
    )
    assert response.status_code == 200
    event = db_session.get(LegalEvent, response.json()["data"]["event_ids"][0])
    assert event.case_id == case_id
    assert event.attribution_status == "confirmed"
    assert event.business_status == "staged"
    assert db_session.scalar(select(BusinessOutbox).where(BusinessOutbox.aggregate_id == event.id)) is None
    assert db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.case_id == case_id)) is None

    approved = client.post(f"/api/v1/legal/events/{event.id}/approve", json={})
    assert approved.status_code == 200
    task = db_session.scalar(select(BusinessOutbox).where(BusinessOutbox.aggregate_id == event.id))
    assert task is not None
    assert task.status == "pending"


def test_partial_full_and_reversed_payment_ledger(client, db_session):
    case_id = _case(client, case_no="（2026）黔0281民初9002号")
    first = client.post(f"/api/v1/legal/cases/{case_id}/payments", json={"amount": "400", "status": "approved"})
    assert first.status_code == 200
    workspace = client.get(f"/api/v1/legal/cases/{case_id}/workspace").json()["data"]
    assert Decimal(workspace["case"]["paid_amount"]) == Decimal("400.00")
    assert workspace["case"]["status"] != "paid"

    second = client.post(f"/api/v1/legal/cases/{case_id}/payments", json={"amount": "600", "status": "approved"})
    assert second.status_code == 200
    workspace = client.get(f"/api/v1/legal/cases/{case_id}/workspace").json()["data"]
    assert Decimal(workspace["case"]["paid_amount"]) == Decimal("1000.00")
    assert workspace["case"]["status"] == "paid"

    reversed_response = client.patch(
        f"/api/v1/legal/cases/{case_id}/payments/{second.json()['data']['id']}",
        json={"action": "reverse", "note": "银行退回"},
    )
    assert reversed_response.status_code == 200
    rows = list(db_session.scalars(select(PaymentRecord).where(PaymentRecord.case_id == case_id)).all())
    assert sum(row.amount for row in rows if row.status == "approved") == Decimal("400.00")
    workspace = client.get(f"/api/v1/legal/cases/{case_id}/workspace").json()["data"]
    assert Decimal(workspace["case"]["paid_amount"]) == Decimal("400.00")
    assert workspace["case"]["status"] != "paid"


def test_unassigned_event_cannot_be_approved(client, db_session):
    response = client.post(
        "/api/v1/legal/messages/mock",
        json={"group_id": "unknown_group", "sender_id": "u1", "msg_type": "text", "content": "请缴费100元"},
    )
    event_id = response.json()["data"]["event_ids"][0]
    approved = client.post(f"/api/v1/legal/events/{event_id}/approve", json={})
    assert approved.status_code == 400
    assert db_session.get(LegalEvent, event_id).business_status == "staged"


def test_attribution_queue_exposes_recognized_fields_and_context(client, db_session):
    group = WeComArchiveGroup(room_id="detail_group", display_name="还款跟进群")
    before = GroupMessage(
        group_id="detail_group",
        sender_id="lawyer",
        msg_type="text",
        content="这是张新宇案件的第一期还款截图",
        raw_payload_json="{}",
        received_at=now_tz() - timedelta(minutes=1),
    )
    image_message = GroupMessage(
        group_id="detail_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add_all([group, before, image_message])
    db_session.flush()
    media = MediaFile(
        group_message_id=image_message.id,
        group_id="detail_group",
        media_type="image",
        mime_type="image/png",
        ocr_status="processed",
        review_status="pending",
        extracted_text="微信支付收款 821.46元",
        ocr_result_json=json.dumps(
            {
                "event_type": "payment_screenshot",
                "amount": "821.46",
                "plaintiff": "广州市番禺区钟村长希炖品店",
                "defendant": "张新宇",
                "metadata": {
                    "structured_fields": {"installment_sequence": 1},
                    "field_sources": {"amount": "OCR原文"},
                },
            },
            ensure_ascii=False,
        ),
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    item = AttributionItem(
        group_id="detail_group",
        subject_type="media",
        subject_id=media.id,
        media_file_id=media.id,
        reason="无法唯一确定案件",
        status="pending",
    )
    db_session.add(item)
    db_session.commit()

    listed = client.get("/api/v1/legal/attribution-queue?limit=100")
    assert listed.status_code == 200
    summary = next(row for row in listed.json()["data"]["items"] if row["id"] == item.id)
    assert summary["group_name"] == "还款跟进群"
    assert summary["event_type"] == "payment_screenshot"
    assert summary["recognized_fields"]["defendant"] == "张新宇"
    assert summary["recognized_fields"]["installment_sequence"] == 1

    detail = client.get(f"/api/v1/legal/attribution-queue/{item.id}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["source_sender_id"] == "operator"
    assert data["ocr_text"] == "微信支付收款 821.46元"
    assert any(row["content"] == "这是张新宇案件的第一期还款截图" for row in data["context_messages"])


def test_media_replaces_same_message_event_as_canonical_attribution_item(db_session):
    message = GroupMessage(
        group_id="bundle_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    event = LegalEvent(
        group_message_id=message.id,
        event_type="payment_screenshot",
        attribution_status="pending",
        business_status="staged",
    )
    media = MediaFile(
        group_message_id=message.id,
        group_id="bundle_group",
        media_type="image",
        source="test",
    )
    db_session.add_all([event, media])
    db_session.flush()

    service = AttributionService(db_session)
    event_item = service.ensure_event(event, group_id="bundle_group")
    media_item = service.ensure_media(media)
    db_session.flush()

    assert event_item.status == "superseded"
    assert media_item.status == "pending"
    assert media_item.media_file_id == media.id
    pending = list(db_session.scalars(select(AttributionItem).where(AttributionItem.status == "pending")).all())
    assert pending == [media_item]


def test_confirming_material_bundle_only_assigns_its_source_message(db_session):
    legal_case = LegalCase(
        case_no="(2026)粤0101民初200号",
        debtor_name="张三",
        group_id="shared_group",
        due_date=date.today() + timedelta(days=10),
        total_amount=Decimal("1000"),
        paid_amount=Decimal("0"),
        status="normal",
    )
    first_message = GroupMessage(group_id="shared_group", sender_id="u1", msg_type="image", raw_payload_json="{}", received_at=now_tz())
    second_message = GroupMessage(group_id="shared_group", sender_id="u2", msg_type="text", content="另一个案件", raw_payload_json="{}", received_at=now_tz())
    db_session.add_all([legal_case, first_message, second_message])
    db_session.flush()
    linked_event = LegalEvent(group_message_id=first_message.id, event_type="payment_screenshot", attribution_status="pending", business_status="staged")
    unrelated_event = LegalEvent(group_message_id=second_message.id, event_type="payment_notice", attribution_status="pending", business_status="staged")
    db_session.add_all([linked_event, unrelated_event])
    db_session.flush()
    media = MediaFile(
        group_message_id=first_message.id,
        group_id="shared_group",
        media_type="image",
        review_status="pending",
        review_event_id=linked_event.id,
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    linked_event.metadata_json = json.dumps({"media_file_id": media.id})
    item = AttributionService(db_session).ensure_media(media)

    result = AttributionService(db_session).batch_confirm([item.id], legal_case.id, "reviewer")

    assert result == {"confirmed": 1, "queued": 0}
    assert media.case_id == legal_case.id
    assert linked_event.case_id == legal_case.id
    assert linked_event.attribution_status == "confirmed"
    assert unrelated_event.case_id is None
    assert unrelated_event.attribution_status == "pending"
    assert db_session.scalar(select(BusinessOutbox)) is None


def test_stage_only_reanalysis_never_creates_business_side_effects(db_session, monkeypatch, tmp_path):
    legal_case = LegalCase(
        case_no="(2026)粤0101民初201号",
        plaintiff_name="甲公司",
        debtor_name="张三",
        group_id="stage_group",
        due_date=date.today() + timedelta(days=10),
        total_amount=Decimal("1000"),
        paid_amount=Decimal("0"),
        status="normal",
    )
    caption = GroupMessage(
        group_id="stage_group",
        sender_id="lawyer",
        msg_type="text",
        content="甲公司+张三+第1期还款+400元",
        raw_payload_json="{}",
        received_at=now_tz() - timedelta(seconds=2),
    )
    image = GroupMessage(group_id="stage_group", sender_id="operator", msg_type="image", raw_payload_json="{}", received_at=now_tz())
    path = tmp_path / "payment.jpg"
    path.write_bytes(b"test")
    db_session.add_all([legal_case, caption, image])
    db_session.flush()
    media = MediaFile(
        group_message_id=image.id,
        group_id="stage_group",
        media_type="image",
        local_path=str(path),
        download_status="downloaded",
        ocr_status="processed",
        review_status="pending",
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    service = MediaFileService(db_session)
    monkeypatch.setattr(
        service.ocr_service,
        "extract_from_file",
        lambda *args, **kwargs: {
            "success": True,
            "raw_text": "微信支付成功 400元",
            "case_no": legal_case.case_no,
            "plaintiff": "甲公司",
            "defendant": "张三",
            "event_type": "payment_screenshot",
            "amount": "400",
            "confidence": 0.99,
            "requires_review": False,
            "review_reasons": [],
            "metadata": {},
        },
    )

    result = service.process_ocr(
        media.id,
        force_reprocess=True,
        stage_only=True,
        preferred_context_message_id=caption.id,
    )

    db_session.refresh(media)
    event = db_session.get(LegalEvent, result["event_id"])
    item = db_session.scalar(select(AttributionItem).where(AttributionItem.media_file_id == media.id, AttributionItem.status == "pending"))
    stored_result = json.loads(media.ocr_result_json)
    assert media.case_id is None
    assert media.review_status == "pending"
    assert event.case_id is None
    assert event.attribution_status == "pending"
    assert event.business_status == "staged"
    assert item is not None
    assert item.suggested_case_id == legal_case.id
    assert stored_result["metadata"]["stage_only_reanalysis"] is True
    assert stored_result["metadata"]["reanalysis_context_message_id"] == caption.id
    assert db_session.scalar(select(BusinessOutbox)) is None
    assert db_session.scalar(select(PaymentRecord)) is None
    assert db_session.scalar(select(Reminder)) is None
    assert db_session.scalar(select(DocumentSyncLog)) is None


def test_outbox_process_is_idempotent(client, db_session):
    case_id = _case(client, case_no="（2026）黔0281民初9003号")
    response = client.post(
        "/api/v1/legal/messages/mock",
        json={"group_id": "workflow_group", "sender_id": "u1", "msg_type": "text", "content": "案件（2026）黔0281民初9003号需要缴费100元"},
    )
    event_id = response.json()["data"]["event_ids"][0]
    client.post(f"/api/v1/legal/events/{event_id}/approve", json={})
    first = OutboxService(db_session).process_pending()
    second = OutboxService(db_session).process_pending()
    db_session.commit()
    assert first["completed"] == 1
    assert second["processed"] == 0
    assert db_session.get(LegalEvent, event_id).business_status == "applied"
    assert len(list(db_session.scalars(select(DocumentSyncLog).where(DocumentSyncLog.case_id == case_id)).all())) >= 1


def test_court_notice_without_case_uploads_summons_and_writes_court_sheet(db_session, tmp_path):
    image_path = tmp_path / "summons.jpg"
    image_path.write_bytes(b"summons-image")
    result = {
        "event_type": "court_notice",
        "document_type": "开庭传票",
        "case_no": None,
        "plaintiff": "测试公司",
        "defendant": "张三",
        "court_time": "2026-08-03T09:30:00+08:00",
        "requires_review": False,
        "metadata": {"structured_fields": {"court_name": "测试人民法院"}},
    }
    media = MediaFile(
        group_id="court_group",
        msg_id="court-msg-1",
        media_type="image",
        original_filename="summons.jpg",
        file_ext=".jpg",
        local_path=str(image_path),
        download_status="downloaded",
        ocr_status="processed",
        review_status="not_required",
        ocr_result_json=json.dumps(result, ensure_ascii=False),
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    event = LegalEvent(
        event_type="court_notice",
        event_time=now_tz(),
        attribution_status="not_required",
        business_status="approved",
        metadata_json=json.dumps({"media_file_id": media.id}, ensure_ascii=False),
    )
    db_session.add(event)
    db_session.flush()
    media.review_event_id = event.id

    BusinessApplicationService(db_session).apply_event(event.id)

    logs = list(db_session.scalars(select(DocumentSyncLog).order_by(DocumentSyncLog.id)).all())
    assert event.business_status == "applied"
    assert media.business_applied_at is not None
    assert [log.sync_type for log in logs] == ["legal_document_upload", "court_time"]
    assert {log.status for log in logs} == {"applied"}
    row = json.loads(logs[1].request_payload_json)["payload"]["row"]
    assert row["被告"] == "张三"
    assert row["开庭时间"] == "2026-08-03T09:30:00+08:00"
    assert row["传票"].startswith("kdocs://")
    assert db_session.scalar(select(Reminder)) is None


def test_court_notice_sheet_failure_keeps_business_unapplied(db_session, tmp_path, monkeypatch):
    image_path = tmp_path / "failed-summons.jpg"
    image_path.write_bytes(b"summons-image")
    result = {
        "event_type": "court_notice",
        "document_type": "开庭传票",
        "defendant": "张三",
        "court_time": "2026-08-03T09:30:00+08:00",
        "requires_review": False,
        "metadata": {},
    }
    media = MediaFile(
        group_id="court_group",
        msg_id="court-msg-failed",
        media_type="image",
        original_filename="failed-summons.jpg",
        file_ext=".jpg",
        local_path=str(image_path),
        download_status="downloaded",
        ocr_status="processed",
        review_status="not_required",
        ocr_result_json=json.dumps(result, ensure_ascii=False),
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    event = LegalEvent(
        event_type="court_notice",
        attribution_status="not_required",
        business_status="approved",
        metadata_json=json.dumps({"media_file_id": media.id}),
    )
    db_session.add(event)
    db_session.flush()
    media.review_event_id = event.id
    service = MediaFileService(db_session)
    monkeypatch.setattr(service, "_upload_court_notice", lambda *_args: "https://kdocs.test/summons.jpg")

    class FailedLog:
        id = 999
        status = "failed"
        error_message = "cell too large"

    monkeypatch.setattr(service.document_sync, "sync_court_time", lambda *_args, **_kwargs: FailedLog())
    monkeypatch.setattr(service.document_sync, "retry_failed_sync", lambda *_args, **_kwargs: FailedLog())

    with pytest.raises(ValueError, match="开庭时间表写入失败"):
        service._apply_ocr_business(media, event, result, None)

    assert event.business_status == "approved"
    assert media.business_applied_at is None


def test_court_notice_ocr_without_case_is_auto_approved(db_session, tmp_path, monkeypatch):
    image_path = tmp_path / "auto-court.jpg"
    image_path.write_bytes(b"court-image")
    message = GroupMessage(
        group_id="court_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    media = MediaFile(
        group_message_id=message.id,
        group_id="court_group",
        msg_id="court-msg-auto",
        media_type="image",
        original_filename="auto-court.jpg",
        file_ext=".jpg",
        local_path=str(image_path),
        download_status="downloaded",
        ocr_status="pending",
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    service = MediaFileService(db_session)
    monkeypatch.setattr(
        service.ocr_service,
        "extract_from_file",
        lambda *_args, **_kwargs: {
            "success": True,
            "raw_text": "测试人民法院传票，被告张三，2026年8月3日9:30开庭",
            "event_type": "court_notice",
            "document_type": "开庭传票",
            "defendant": "张三",
            "court_time": "2026-08-03T09:30:00+08:00",
            "requires_review": False,
            "metadata": {"structured_fields": {"court_name": "测试人民法院"}},
        },
    )

    service.process_ocr(media.id)

    event = db_session.get(LegalEvent, media.review_event_id)
    assert media.review_status == "not_required"
    assert event.case_id is None
    assert event.attribution_status == "not_required"
    assert event.business_status == "approved"
    assert db_session.scalar(select(AttributionItem)) is None
    assert db_session.scalar(select(BusinessOutbox).where(BusinessOutbox.aggregate_id == event.id)) is not None


def test_judgment_without_case_uploads_document_and_writes_enforcement_sheet(db_session, tmp_path):
    document_path = tmp_path / "judgment.pdf"
    document_path.write_bytes(b"judgment-pdf")
    result = {
        "event_type": "judgment",
        "document_type": "判决书",
        "case_no": "(2026)陕0423民初1531号",
        "plaintiff": "天津乔洋商贸有限公司",
        "defendant": "佐宇航",
        "amount": "7615.21",
        "requires_review": False,
        "metadata": {
            "structured_fields": {
                "identity_number": "610000199001011234",
                "document_date": "2026-07-20",
                "repayment_due_date": "2026-08-05",
                "court_name": "泾阳县人民法院",
            }
        },
    }
    media = MediaFile(
        group_id="legal_document_group",
        msg_id="judgment-msg-1",
        media_type="pdf",
        original_filename="judgment.pdf",
        file_ext=".pdf",
        local_path=str(document_path),
        download_status="downloaded",
        ocr_status="processed",
        review_status="not_required",
        ocr_result_json=json.dumps(result, ensure_ascii=False),
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    event = LegalEvent(
        event_type="judgment",
        event_time=now_tz(),
        attribution_status="not_required",
        business_status="approved",
        metadata_json=json.dumps({"media_file_id": media.id}, ensure_ascii=False),
    )
    db_session.add(event)
    db_session.flush()
    media.review_event_id = event.id

    BusinessApplicationService(db_session).apply_event(event.id)

    logs = list(db_session.scalars(select(DocumentSyncLog).order_by(DocumentSyncLog.id)).all())
    assert event.case_id is None
    assert event.business_status == "applied"
    assert media.business_applied_at is not None
    assert [log.sync_type for log in logs] == ["legal_document_upload", "enforcement_progress"]
    assert {log.status for log in logs} == {"applied"}
    row = json.loads(logs[1].request_payload_json)["payload"]["row"]
    assert row["案号"] == "(2026)陕0423民初1531号"
    assert row["原告"] == "天津乔洋商贸有限公司"
    assert row["被告"] == "佐宇航"
    assert row["文书类型"] == "判决书"
    assert row["总金额"] == "7615.21"
    assert row["已还欠款"] == "0.00"
    assert row["提交情况"] == "未提交"
    assert row["文件链接"].startswith("kdocs://")
    assert str(tmp_path) not in row["文件链接"]


def test_complete_judgment_ocr_without_case_is_auto_approved(db_session, tmp_path, monkeypatch):
    document_path = tmp_path / "mediation.pdf"
    document_path.write_bytes(b"mediation-pdf")
    message = GroupMessage(
        group_id="legal_document_group",
        sender_id="operator",
        msg_type="file",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    existing_case = LegalCase(
        case_no="(2026)川0521民初2440号",
        plaintiff_name="金尚华电器百货店",
        debtor_name="朱俊豪",
        group_id=message.group_id,
        due_date=date.today() + timedelta(days=10),
        total_amount=Decimal("6619.99"),
        paid_amount=Decimal("0"),
        status="normal",
    )
    db_session.add(existing_case)
    db_session.flush()
    media = MediaFile(
        group_message_id=message.id,
        group_id=message.group_id,
        msg_id="mediation-msg-auto",
        media_type="pdf",
        original_filename="mediation.pdf",
        file_ext=".pdf",
        local_path=str(document_path),
        download_status="downloaded",
        ocr_status="pending",
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    service = MediaFileService(db_session)
    monkeypatch.setattr(
        service.ocr_service,
        "extract_from_file",
        lambda *_args, **_kwargs: {
            "success": True,
            "raw_text": "四川省泸县人民法院 民事调解书 (2026)川0521民初2440号 原告金尚华电器百货店 被告朱俊豪 本院审理终结，双方达成调解协议",
            "event_type": "judgment",
            "document_type": "调解书",
            "case_no": "(2026)川0521民初2440号",
            "plaintiff": "金尚华电器百货店",
            "defendant": "朱俊豪",
            "amount": "6619.99",
            "confidence": 0.99,
            "extraction_confidence": 0.70,
            "requires_review": True,
            "review_reasons": ["文书落款日期缺失"],
            "metadata": {
                "review_reasons": ["文书落款日期缺失"],
                "structured_fields": {"court_name": "泸县人民法院"},
            },
        },
    )

    service.process_ocr(media.id)

    event = db_session.get(LegalEvent, media.review_event_id)
    assert media.case_id is None
    assert media.review_status == "not_required"
    assert event.case_id is None
    assert event.attribution_status == "not_required"
    assert event.business_status == "approved"
    assert db_session.scalar(select(AttributionItem)) is None
    assert db_session.scalar(select(BusinessOutbox).where(BusinessOutbox.aggregate_id == event.id)) is not None


def test_false_positive_legal_document_spreadsheet_stays_pending(db_session, tmp_path, monkeypatch):
    document_path = tmp_path / "ambiguous.png"
    document_path.write_bytes(b"spreadsheet-screenshot")
    message = GroupMessage(
        group_id="legal_document_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    media = MediaFile(
        group_message_id=message.id,
        group_id=message.group_id,
        media_type="image",
        local_path=str(document_path),
        download_status="downloaded",
        ocr_status="pending",
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    service = MediaFileService(db_session)
    monkeypatch.setattr(
        service.ocr_service,
        "extract_from_file",
        lambda *_args, **_kwargs: {
            "success": True,
            "raw_text": "人民法院调解书信息统计表 (2026)川0521民初2440号 原告甲公司 被告张三",
            "event_type": "judgment",
            "document_type": "调解书",
            "case_no": "(2026)川0521民初2440号",
            "plaintiff": "甲公司",
            "defendant": "张三",
            "confidence": 0.99,
            "extraction_confidence": 0.95,
            "requires_review": True,
            "review_reasons": ["疑似表格截图，并非正式法律文书"],
            "metadata": {"review_reasons": ["疑似表格截图，并非正式法律文书"]},
        },
    )

    service.process_ocr(media.id)

    event = db_session.get(LegalEvent, media.review_event_id)
    assert media.review_status == "pending"
    assert event.business_status == "staged"
    assert db_session.scalar(select(BusinessOutbox).where(BusinessOutbox.aggregate_id == event.id)) is None
    assert db_session.scalar(select(DocumentSyncLog)) is None


def test_judgment_upload_failure_keeps_business_unapplied(db_session, tmp_path, monkeypatch):
    document_path = tmp_path / "failed-judgment.pdf"
    document_path.write_bytes(b"judgment-pdf")
    result = {
        "event_type": "judgment",
        "document_type": "判决书",
        "case_no": "(2026)陕0423民初1531号",
        "plaintiff": "天津乔洋商贸有限公司",
        "defendant": "佐宇航",
        "requires_review": False,
        "metadata": {},
    }
    media = MediaFile(
        group_id="legal_document_group",
        media_type="pdf",
        local_path=str(document_path),
        download_status="downloaded",
        ocr_status="processed",
        review_status="not_required",
        ocr_result_json=json.dumps(result, ensure_ascii=False),
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    event = LegalEvent(
        event_type="judgment",
        attribution_status="not_required",
        business_status="approved",
        metadata_json=json.dumps({"media_file_id": media.id}),
    )
    db_session.add(event)
    db_session.flush()
    media.review_event_id = event.id
    service = MediaFileService(db_session)

    class FailedLog:
        id = 999
        status = "failed"
        error_message = "upload unavailable"

    monkeypatch.setattr(service.document_sync, "sync_legal_document_upload", lambda *_args, **_kwargs: FailedLog())
    monkeypatch.setattr(service.document_sync, "retry_failed_sync", lambda *_args, **_kwargs: FailedLog())

    with pytest.raises(ValueError, match="法律文书上传失败"):
        service._apply_ocr_business(media, event, result, None)

    assert event.business_status == "approved"
    assert media.business_applied_at is None


def test_summons_layout_fallback_stages_unknown_ai_result_for_review(db_session, tmp_path, monkeypatch):
    image_path = tmp_path / "fallback-summons.jpg"
    image_path.write_bytes(b"court-image")
    message = GroupMessage(
        group_id="fallback_court_group",
        sender_id="operator",
        msg_type="image",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    media = MediaFile(
        group_message_id=message.id,
        group_id=message.group_id,
        msg_id="fallback-court-msg",
        media_type="image",
        local_path=str(image_path),
        download_status="downloaded",
        ocr_status="pending",
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    service = MediaFileService(db_session)
    monkeypatch.setattr(
        service.ocr_service,
        "extract_from_file",
        lambda *_args, **_kwargs: {
            "success": True,
            "raw_text": "尉犁县人民法院\n传\n票\n被传唤人\n被传事由 开庭\n应到时间 2026年8月3日\n应到处所 第7号审判庭",
            "event_type": "unknown",
            "document_type": None,
            "defendant": None,
            "court_time": None,
            "requires_review": False,
            "review_reasons": [],
            "metadata": {},
        },
    )

    summary = service.process_ocr(media.id)

    stored = json.loads(media.ocr_result_json)
    event = db_session.get(LegalEvent, media.review_event_id)
    assert summary["event_type"] == "court_notice"
    assert stored["document_type"] == "开庭传票"
    assert stored["metadata"]["court_summons_fallback"] is True
    assert media.review_status == "pending"
    assert event.attribution_status == "not_required"
    assert event.business_status == "staged"
    assert db_session.scalar(select(BusinessOutbox).where(BusinessOutbox.aggregate_id == event.id)) is None


def test_non_summons_unknown_result_is_not_promoted():
    result = {"event_type": "unknown", "metadata": {}}

    promoted = MediaFileService._promote_suspected_court_notice(result, "普通付款截图，金额 500 元")

    assert promoted is False
    assert result["event_type"] == "unknown"


def test_court_party_defaults_swap_company_and_summoned_person():
    result = {
        "event_type": "court_notice",
        "plaintiff": "张三",
        "defendant": "杭州测试科技有限公司",
        "metadata": {},
    }

    changed = MediaFileService._apply_court_party_defaults(result)

    assert changed is True
    assert result["plaintiff"] == "杭州测试科技有限公司"
    assert result["defendant"] == "张三"
    assert result["metadata"]["court_party_default_applied"] is True


def test_court_party_defaults_move_business_to_plaintiff_and_require_person():
    result = {
        "event_type": "court_notice",
        "plaintiff": None,
        "defendant": "可可店经营部（个体工商户）",
        "requires_review": False,
        "metadata": {},
    }

    changed = MediaFileService._apply_court_party_defaults(result)

    assert changed is True
    assert result["plaintiff"] == "可可店经营部（个体工商户）"
    assert result["defendant"] is None
    assert result["requires_review"] is True
    assert "请确认被传唤人姓名" in result["review_reasons"][0]


def test_court_party_defaults_do_not_change_non_summons():
    result = {"event_type": "judgment", "plaintiff": "张三", "defendant": "测试公司"}

    assert MediaFileService._apply_court_party_defaults(result) is False
    assert result == {"event_type": "judgment", "plaintiff": "张三", "defendant": "测试公司"}


def test_corrected_court_notice_without_case_exits_attribution_queue(db_session, tmp_path):
    image_path = tmp_path / "corrected-court.jpg"
    image_path.write_bytes(b"court-image")
    result = {
        "event_type": "court_notice",
        "document_type": "开庭传票",
        "defendant": None,
        "court_time": "2026-08-03T09:00:00+08:00",
        "requires_review": True,
        "metadata": {},
    }
    media = MediaFile(
        group_id="court_group",
        media_type="image",
        local_path=str(image_path),
        download_status="downloaded",
        ocr_status="processed",
        review_status="pending",
        ocr_result_json=json.dumps(result, ensure_ascii=False),
        source="test",
    )
    db_session.add(media)
    db_session.flush()
    event = LegalEvent(
        event_type="court_notice",
        attribution_status="pending",
        business_status="staged",
        metadata_json=json.dumps({"media_file_id": media.id}),
    )
    db_session.add(event)
    db_session.flush()
    media.review_event_id = event.id
    item = AttributionService(db_session).ensure_media(media)

    MediaFileService(db_session).decide_ocr_review(
        media.id,
        "corrected",
        "reviewer",
        corrections={
            "plaintiff": "张三",
            "defendant": "测试科技有限公司",
            "court_name": "尉犁县人民法院",
            "court_room": "第7号审判庭",
            "hearing_mode": "现场开庭",
            "judge_phone": "0996-1234567",
        },
    )

    assert media.review_status == "corrected"
    assert event.case_id is None
    assert event.attribution_status == "not_required"
    assert event.business_status == "approved"
    assert item.status == "superseded"
    stored = json.loads(media.review_result_json)
    assert stored["plaintiff"] == "测试科技有限公司"
    assert stored["defendant"] == "张三"
    assert stored["metadata"]["structured_fields"] == {
        "court_name": "尉犁县人民法院",
        "court_room": "第7号审判庭",
        "hearing_mode": "现场开庭",
        "judge_phone": "0996-1234567",
    }
    assert db_session.scalar(select(BusinessOutbox).where(BusinessOutbox.aggregate_id == event.id)) is not None


def test_approved_text_repayment_plan_creates_installment_schedule(client, db_session):
    case_id = _case(client, case_no="（2026）黔0281民初9004号")
    event = LegalEvent(
        case_id=case_id,
        event_type="repayment_agreement",
        attribution_status="confirmed",
        business_status="approved",
        metadata_json=json.dumps(
            {
                "structured_fields": {
                    "repayment_plan": {
                        "installments": [
                            {"sequence": 1, "due_date": "2026-09-01", "amount": 500},
                            {"sequence": 2, "due_date": "2026-10-01", "amount": 500},
                        ]
                    }
                }
            }
        ),
    )
    db_session.add(event)
    db_session.flush()

    BusinessApplicationService(db_session).apply_event(event.id)

    reminders = list(
        db_session.scalars(
            select(Reminder).where(
                Reminder.case_id == case_id,
                Reminder.reminder_type == "installment_repayment",
            )
        ).all()
    )
    assert len(reminders) == 6
    assert event.business_status == "applied"
