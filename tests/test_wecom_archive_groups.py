from datetime import datetime

from sqlalchemy import select

from app.adapters.wecom_archive import WeComArchiveAdapter
from app.models.group_message import GroupMessage
from app.models.media_file import MediaFile
from app.models.wecom_archive_group import WeComArchiveGroup
from app.schemas.legal import WeComArchiveGroupCreate, WeComArchiveGroupUpdate
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.seq_store import SeqStore


def _message(seq: int, room_id: str | None = "wr_legal_001", msgtype: str = "text") -> dict[str, object]:
    message: dict[str, object] = {
        "seq": seq,
        "msgid": f"msg_{seq}",
        "from": "user_001",
        "msgtype": msgtype,
        "msgtime": 1780300000000,
    }
    if room_id is not None:
        message["roomid"] = room_id
    if msgtype == "text":
        message["text"] = {"content": "归档范围测试"}
    else:
        message["image"] = {"md5sum": "abc", "filesize": 123}
    return message


def _adapter(tmp_path) -> WeComArchiveAdapter:
    return WeComArchiveAdapter(seq_store=SeqStore(str(tmp_path / "archive-seq.txt")))


def test_unknown_group_is_discovered_without_storing_message_content(db_session, tmp_path):
    adapter = _adapter(tmp_path)

    result = adapter.process_messages(
        db_session,
        [_message(1)],
        enforce_group_scope=True,
    )
    db_session.commit()

    group = db_session.scalar(select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == "wr_legal_001"))
    assert result == {
        "pulled": 1,
        "processed": 0,
        "failed": 0,
        "skipped": 1,
        "discovered": 1,
        "identified": 0,
        "last_seq": 1,
    }
    assert group is not None
    assert group.status == "discovered"
    assert group.seen_message_count == 1
    assert db_session.scalar(select(GroupMessage)) is None


def test_enabled_group_is_processed_and_uses_tenant_mapping(client, db_session, tmp_path):
    tenant_response = client.post(
        "/api/v1/legal/tenants",
        json={"tenant_id": "tenant_001", "tenant_name": "致和法务"},
    )
    assert tenant_response.status_code == 200
    group_response = client.post(
        "/api/v1/legal/wecom-archive/groups",
        json={
            "room_id": "wr_legal_001",
            "display_name": "法务测试群",
            "tenant_id": "tenant_001",
            "status": "enabled",
        },
    )
    assert group_response.status_code == 200

    result = _adapter(tmp_path).process_messages(
        db_session,
        [_message(2)],
        enforce_group_scope=True,
    )
    db_session.commit()

    stored = db_session.scalar(select(GroupMessage).where(GroupMessage.group_id == "wr_legal_001"))
    assert result["processed"] == 1
    assert result["skipped"] == 0
    assert result["discovered"] == 0
    assert stored is not None
    assert stored.tenant_id == "tenant_001"
    assert stored.content == "归档范围测试"


def test_disabled_group_skips_media_before_download(db_session, tmp_path):
    WeComArchiveGroupService(db_session).create_group(
        WeComArchiveGroupCreate(room_id="wr_disabled", status="disabled")
    )
    db_session.commit()

    result = _adapter(tmp_path).process_messages(
        db_session,
        [_message(3, room_id="wr_disabled", msgtype="image")],
        enforce_group_scope=True,
    )
    db_session.commit()

    assert result["skipped"] == 1
    assert db_session.scalar(select(GroupMessage)) is None
    assert db_session.scalar(select(MediaFile)) is None


def test_direct_message_without_room_id_is_skipped_without_discovery(db_session, tmp_path):
    result = _adapter(tmp_path).process_messages(
        db_session,
        [_message(4, room_id=None)],
        enforce_group_scope=True,
    )
    db_session.commit()

    assert result["skipped"] == 1
    assert result["discovered"] == 0
    assert result["last_seq"] == 4
    assert db_session.scalar(select(WeComArchiveGroup)) is None


def test_identification_message_names_discovered_group_without_storing_content(db_session, tmp_path):
    message = _message(5, room_id="wr_to_identify")
    message["text"] = {"content": "#群名识别群  致和法务执行一群  "}

    result = _adapter(tmp_path).process_messages(
        db_session,
        [message],
        enforce_group_scope=True,
    )
    db_session.commit()

    group = db_session.scalar(select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == "wr_to_identify"))
    assert result["discovered"] == 1
    assert result["identified"] == 1
    assert result["skipped"] == 1
    assert group is not None
    assert group.display_name == "致和法务执行一群"
    assert group.status == "discovered"
    assert db_session.scalar(select(GroupMessage)) is None


def test_identification_message_renames_enabled_group_without_changing_status(db_session, tmp_path):
    group = WeComArchiveGroupService(db_session).create_group(
        WeComArchiveGroupCreate(
            room_id="wr_enabled",
            display_name="已确认法务群",
            status="enabled",
        )
    )
    db_session.commit()
    message = _message(6, room_id="wr_enabled")
    message["text"] = {"content": "#群名识别群 新法务群名"}

    result = _adapter(tmp_path).process_messages(
        db_session,
        [message],
        enforce_group_scope=True,
    )
    db_session.commit()

    db_session.refresh(group)
    assert result["identified"] == 1
    assert result["skipped"] == 1
    assert group.display_name == "新法务群名"
    assert group.status == "enabled"
    assert db_session.scalar(select(GroupMessage)) is None


def test_archive_group_api_can_update_discovered_group(client, db_session):
    WeComArchiveGroupService(db_session).discover_group(
        "wr_discovered",
        datetime.fromisoformat(WeComArchiveAdapter._normalize_received_at(1780300000000)),
    )
    db_session.commit()

    response = client.patch(
        "/api/v1/legal/wecom-archive/groups/wr_discovered",
        json={"display_name": "执行案件群", "wecomapi_room_id": "1081379876227242", "status": "enabled"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["display_name"] == "执行案件群"
    assert response.json()["data"]["wecomapi_room_id"] == "1081379876227242"
    assert response.json()["data"]["status"] == "enabled"

    rename_response = client.patch(
        "/api/v1/legal/wecom-archive/groups/wr_discovered",
        json={"display_name": "执行案件一群"},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["data"]["display_name"] == "执行案件一群"

    list_response = client.get("/api/v1/legal/wecom-archive/groups")
    assert list_response.status_code == 200
    assert list_response.json()["data"]["total"] == 1


def test_matching_group_names_auto_onboard_with_policy_overrides(db_session):
    service = WeComArchiveGroupService(db_session)
    merchant = service.create_group(
        WeComArchiveGroupCreate(room_id="wr_merchant", display_name="一号法务起诉沟通群", status="discovered")
    )
    debtor = service.create_group(
        WeComArchiveGroupCreate(room_id="wr_debtor", display_name="张三还款对接群", status="discovered")
    )
    blocked = service.create_group(
        WeComArchiveGroupCreate(
            room_id="wr_blocked",
            display_name="二号法务起诉沟通群",
            access_policy="blacklist",
        )
    )

    assert (merchant.status, merchant.group_type) == ("enabled", "merchant")
    assert (debtor.status, debtor.group_type) == ("enabled", "debtor")
    assert blocked.status == "disabled"

    service.update_group(
        "wr_blocked",
        WeComArchiveGroupUpdate(access_policy="whitelist"),
    )
    assert blocked.status == "enabled"
