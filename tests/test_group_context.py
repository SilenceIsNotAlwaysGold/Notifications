import json
from datetime import date, timedelta
from decimal import Decimal

from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.media_file import MediaFile
from app.models.wecom_archive_group import WeComArchiveGroup
from app.services.group_context_service import GroupContextService
from app.services.media_file_service import MediaFileService
from app.utils.datetime_utils import now_tz


def _message(group_id: str, sender_id: str, content: str | None, received_at):
    return GroupMessage(
        group_id=group_id,
        sender_id=sender_id,
        msg_type="text" if content else "image",
        content=content,
        raw_payload_json="{}",
        received_at=received_at,
    )


def test_context_window_uses_same_group_and_orders_messages_around_material(db_session):
    anchor_time = now_tz()
    before = _message("group_001", "lawyer", "这是（2026）黔0281民初9001号的材料", anchor_time - timedelta(minutes=2))
    anchor = _message("group_001", "merchant", None, anchor_time)
    after = _message("group_001", "merchant", "这是缴费通知，请安排处理", anchor_time + timedelta(minutes=1))
    other_group = _message("group_002", "other", "（2026）黔0281民初9999号", anchor_time - timedelta(minutes=1))
    too_old = _message("group_001", "old", "（2025）黔0281民初1000号", anchor_time - timedelta(days=4))
    db_session.add_all([before, anchor, after, other_group, too_old])
    db_session.flush()

    context = GroupContextService(db_session).around_message(anchor.id)

    assert [item["message_id"] for item in context] == [before.id, after.id]
    assert [item["position"] for item in context] == ["before", "after"]
    assert context[0]["sender_id"] == "lawyer"
    assert "9001号" in context[0]["content"]


def test_context_window_is_bounded_on_each_side(db_session):
    anchor_time = now_tz()
    messages = [
        _message("group_001", f"sender-{index}", f"消息 {index}", anchor_time + timedelta(minutes=index))
        for index in range(-4, 5)
        if index != 0
    ]
    anchor = _message("group_001", "merchant", None, anchor_time)
    db_session.add_all([*messages, anchor])
    db_session.flush()

    context = GroupContextService(db_session).around_message(anchor.id, before_count=2, after_count=1)

    assert [item["content"] for item in context] == ["消息 -2", "消息 -1", "消息 1"]


def test_context_includes_group_case_metadata_and_adjacent_attachment_ocr(db_session):
    anchor_time = now_tz()
    adjacent = _message("group_001", "merchant", None, anchor_time - timedelta(minutes=3))
    anchor = _message("group_001", "merchant", None, anchor_time)
    db_session.add_all(
        [
            adjacent,
            anchor,
            WeComArchiveGroup(room_id="group_001", display_name="致和执行一群", status="enabled"),
            LegalCase(
                case_no="(2026)黔0281民初9001号",
                debtor_name="张三",
                group_id="group_001",
                due_date=date(2026, 8, 31),
                total_amount=Decimal("1000"),
                paid_amount=Decimal("0"),
                status="normal",
            ),
        ]
    )
    db_session.flush()
    db_session.add(
        MediaFile(
            group_message_id=adjacent.id,
            group_id="group_001",
            media_type="image",
            download_status="downloaded",
            ocr_status="processed",
            extracted_text="身份证明 张三",
            source="mock",
        )
    )
    db_session.flush()

    context = GroupContextService(db_session).around_message(anchor.id)

    assert context[0]["position"] == "metadata"
    assert "群名称：致和执行一群" in context[0]["content"]
    assert "(2026)黔0281民初9001号" in context[0]["content"]
    assert context[1]["msg_type"] == "image"
    assert context[1]["content"] == "[相邻图片 OCR摘要] 身份证明 张三"


def test_context_prefers_nearest_messages_within_character_budget(db_session):
    anchor_time = now_tz()
    far = _message("group_001", "far", "远消息" * 20, anchor_time - timedelta(hours=2))
    near = _message("group_001", "near", "近消息" * 20, anchor_time - timedelta(minutes=1))
    anchor = _message("group_001", "merchant", None, anchor_time)
    db_session.add_all([far, near, anchor])
    db_session.flush()

    context = GroupContextService(db_session).around_message(anchor.id, max_total_chars=30)

    assert len(context) == 1
    assert context[0]["message_id"] == near.id
    assert len(context[0]["content"]) == 30


def test_case_number_message_reanalyzes_nearest_pending_material(db_session, monkeypatch):
    anchor_time = now_tz()
    anchor = _message("group_001", "merchant", None, anchor_time)
    current = _message(
        "group_001",
        "lawyer",
        "补充案号：（2026）黔0281民初9001号",
        anchor_time + timedelta(minutes=2),
    )
    db_session.add_all([anchor, current])
    db_session.flush()
    media = MediaFile(
        group_message_id=anchor.id,
        group_id="group_001",
        media_type="image",
        download_status="downloaded",
        ocr_status="processed",
        review_status="pending",
        ocr_result_json=json.dumps({"case_no": None, "context_messages": []}),
        source="mock",
    )
    db_session.add(media)
    db_session.flush()
    captured = {}

    def fake_process(self, media_file_id, trigger_type="system", operator=None):
        captured.update(media_file_id=media_file_id, trigger_type=trigger_type, operator=operator)
        return {"media_file_id": media_file_id}

    monkeypatch.setattr(MediaFileService, "process_ocr", fake_process)

    result = MediaFileService(db_session).reanalyze_recent_pending_with_context(
        current,
        "（2026）黔0281民初9001号",
    )

    assert result == {"media_file_id": media.id}
    assert captured == {
        "media_file_id": media.id,
        "trigger_type": "context_message",
        "operator": "system:group-context",
    }


def test_context_reanalysis_skips_material_that_already_used_message(db_session, monkeypatch):
    anchor_time = now_tz()
    anchor = _message("group_001", "merchant", None, anchor_time)
    current = _message("group_001", "lawyer", "补充案号", anchor_time + timedelta(minutes=2))
    db_session.add_all([anchor, current])
    db_session.flush()
    media = MediaFile(
        group_message_id=anchor.id,
        group_id="group_001",
        media_type="image",
        download_status="downloaded",
        ocr_status="processed",
        review_status="pending",
        ocr_result_json=json.dumps({"case_no": None, "context_messages": [{"message_id": current.id}]}),
        source="mock",
    )
    db_session.add(media)
    db_session.flush()
    monkeypatch.setattr(MediaFileService, "process_ocr", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应重复分析")))

    result = MediaFileService(db_session).reanalyze_recent_pending_with_context(current, "（2026）黔0281民初9001号")

    assert result is None
