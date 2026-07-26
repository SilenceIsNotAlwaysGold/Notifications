import json
from datetime import date, timedelta
from decimal import Decimal

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
    assert media.case_id is None
    assert media.review_status == "pending"
    assert event.case_id is None
    assert event.attribution_status == "pending"
    assert event.business_status == "staged"
    assert item is not None
    assert item.suggested_case_id == legal_case.id
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
