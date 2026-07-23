import json

import httpx

from app.core.config import get_settings
from app.models.wecom_archive_group import WeComArchiveGroup
from app.models.wecomapi_room_cache import WeComApiRoomCache
from app.models.wecomapi_room_member_cache import WeComApiRoomMemberCache
from app.adapters.wecomapi import WeComApiAdapter
from app.adapters.wecom_message import WeComMessageAdapter
from app.services.wecomapi_settings_service import WeComApiSettingsService
from app.schemas.wecomapi_settings import WeComApiSettingsUpdate


def test_wecomapi_settings_api_masks_token(client, monkeypatch):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://manager.wecomapi.com")
    monkeypatch.setenv("WECOMAPI_API_PATH", "/wecom/finder/api")
    monkeypatch.setenv("WECOMAPI_TOKEN", "SECRET_WECOMAPI_TOKEN")
    monkeypatch.setenv("WECOMAPI_GUID", "device-guid")
    get_settings.cache_clear()

    response = client.get("/api/v1/legal/wecomapi-settings", headers={"host": "zhihefawu.chat"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["has_token"] is True
    assert data["token_mask"] == "******"
    assert data["guid"] == "device-guid"
    assert data["callback_url"] == "http://zhihefawu.chat/api/v1/wecomapi/callback"
    assert "SECRET_WECOMAPI_TOKEN" not in response.text


def test_wecomapi_settings_update_writes_whitelisted_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=production",
                "WECOM_SEND_MODE=mock",
                "WECOMAPI_TOKEN=old-token",
                "WECOMAPI_GUID=old-guid",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WECOM_SEND_MODE", "mock")
    monkeypatch.setenv("WECOMAPI_TOKEN", "old-token")
    monkeypatch.setenv("WECOMAPI_GUID", "old-guid")
    get_settings.cache_clear()

    service = WeComApiSettingsService(get_settings(), env_file=env_file)
    service.update(
        WeComApiSettingsUpdate(
            send_mode="wecomapi",
            base_url="https://manager.wecomapi.com",
            api_path="wecom/finder/api",
            token_header="WECOM-TOKEN",
            token="new-token",
            guid="new-guid",
        )
    )

    written = env_file.read_text(encoding="utf-8")
    assert "APP_ENV=production" in written
    assert "WECOM_SEND_MODE=wecomapi" in written
    assert "WECOMAPI_BASE_URL=https://manager.wecomapi.com" in written
    assert "WECOMAPI_API_PATH=/wecom/finder/api" in written
    assert "WECOMAPI_TOKEN=new-token" in written
    assert "WECOMAPI_GUID=new-guid" in written
    assert get_settings().wecomapi_guid == "new-guid"
    assert list(tmp_path.glob(".env.bak.*"))


def test_wecomapi_check_login_reports_expired_status(monkeypatch):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://manager.wecomapi.com")
    monkeypatch.setenv("WECOMAPI_API_PATH", "/wecom/finder/api")
    monkeypatch.setenv("WECOMAPI_TOKEN", "sender-token")
    monkeypatch.setenv("WECOMAPI_GUID", "device-guid")
    get_settings.cache_clear()

    def fake_post(url, headers, json, timeout):
        assert url == "https://manager.wecomapi.com/wecom/finder/api"
        assert headers["WECOM-TOKEN"] == "sender-token"
        assert json == {"method": "/login/checkLogin", "params": {"guid": "device-guid"}}
        return httpx.Response(200, json={"code": 1001, "msg": "登录态已过期，请重新登录"})

    monkeypatch.setattr("app.services.wecomapi_settings_service.httpx.post", fake_post)

    status = WeComApiSettingsService(get_settings()).check_login()

    assert status.configured is True
    assert status.online is False
    assert status.stage == "login_expired"
    assert status.vendor_code == 1001
    assert status.vendor_message == "登录态已过期，请重新登录"


def test_wecomapi_check_login_accepts_successful_identity_response(monkeypatch):
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://manager.wecomapi.com")
    monkeypatch.setenv("WECOMAPI_TOKEN", "sender-token")
    monkeypatch.setenv("WECOMAPI_GUID", "device-guid")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.services.wecomapi_settings_service.httpx.post",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={"code": 0, "msg": "成功", "data": {"nickname": "正式发送账号"}},
        ),
    )

    status = WeComApiSettingsService(get_settings()).check_login()

    assert status.online is True
    assert status.stage == "logged_in"
    assert status.account_name == "正式发送账号"


def test_wecomapi_settings_audit_does_not_record_token(client, db_session, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("app.services.wecomapi_settings_service.DEFAULT_ENV_FILE", env_file)

    response = client.put(
        "/api/v1/legal/wecomapi-settings",
        json={"token": "SECRET_UI_TOKEN", "guid": "device-guid"},
    )

    assert response.status_code == 200
    assert "SECRET_UI_TOKEN" not in response.text
    from app.models.operation_audit_log import OperationAuditLog
    from sqlalchemy import select

    audit_log = db_session.scalar(
        select(OperationAuditLog).where(OperationAuditLog.path == "/api/v1/legal/wecomapi-settings")
    )
    assert audit_log is not None
    summary = json.loads(audit_log.request_summary_json)
    assert summary["json"]["token"] == "***"
    assert "SECRET_UI_TOKEN" not in audit_log.request_summary_json


def test_wecomapi_group_sync_updates_mapped_name_and_returns_safe_inventory(client, db_session, monkeypatch):
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://manager.wecomapi.com")
    monkeypatch.setenv("WECOMAPI_TOKEN", "sender-token")
    monkeypatch.setenv("WECOMAPI_GUID", "device-guid")
    get_settings.cache_clear()
    mapped = WeComArchiveGroup(
        room_id="wr_archive_001",
        wecomapi_room_id="room-1",
        display_name="旧群名",
        status="enabled",
    )
    db_session.add(mapped)
    db_session.commit()

    monkeypatch.setattr(
        WeComApiAdapter,
        "list_rooms",
        lambda self: {
            "success": True,
            "rooms": [
                {
                    "roomId": "room-1",
                    "roomName": "执行案件一群",
                    "roomOwnerId": "owner-1",
                    "roomMemberCount": 8,
                    "roomAvatarUrl": "https://example.test/avatar.png",
                    "roomCreateTime": "1773381872",
                },
                {"roomId": "room-2", "roomName": "尚未映射群", "roomMemberCount": 3},
            ],
        },
    )

    response = client.post("/api/v1/legal/wecomapi-settings/sync-groups")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["fetched"] == 2
    assert data["mapped"] == 1
    assert data["updated"] == 1
    assert data["rooms"][0] == {
        "room_id": "room-1",
        "room_name": "执行案件一群",
        "owner_userid": "owner-1",
        "member_count": 8,
        "avatar_url": "https://example.test/avatar.png",
        "created_at": "1773381872",
        "updated_at": None,
    }
    db_session.refresh(mapped)
    assert mapped.display_name == "执行案件一群"
    assert "sender-token" not in response.text


def test_wecomapi_group_sync_uses_callback_cache_when_room_list_is_empty(client, db_session, monkeypatch):
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://manager.wecomapi.com")
    monkeypatch.setenv("WECOMAPI_TOKEN", "sender-token")
    monkeypatch.setenv("WECOMAPI_GUID", "device-guid")
    get_settings.cache_clear()
    db_session.add(WeComApiRoomCache(guid="device-guid", room_id="room-from-callback", source="callback"))
    db_session.commit()

    monkeypatch.setattr(WeComApiAdapter, "list_rooms", lambda self: {"success": True, "rooms": []})
    monkeypatch.setattr(
        WeComApiAdapter,
        "get_room_details",
        lambda self, room_ids: {
            "success": True,
            "rooms": [
                {
                    "roomId": room_ids[0],
                    "roomName": "",
                    "roomCreateUserId": "owner-1",
                    "memberList": [{"userId": "member-1"}, {"userId": "member-2"}],
                }
            ],
        },
    )

    response = client.post("/api/v1/legal/wecomapi-settings/sync-groups")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["fetched"] == 1
    assert data["rooms"][0]["room_id"] == "room-from-callback"
    assert data["rooms"][0]["room_name"] is None
    assert data["rooms"][0]["member_count"] == 2
    assert data["rooms"][0]["owner_userid"] == "owner-1"


def test_wecomapi_test_send_uses_saved_archive_mapping(client, monkeypatch):
    captured = {}

    def fake_send(self, group_id, content, **kwargs):
        captured.update({"group_id": group_id, "content": content})
        return {"success": True, "mode": "wecomapi", "status_code": 200}

    monkeypatch.setattr(WeComMessageAdapter, "send_text", fake_send)

    response = client.post(
        "/api/v1/legal/wecomapi-settings/test-send",
        json={"room_id": "wr_archive_test"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"success": True, "mode": "wecomapi", "status_code": 200}
    assert captured == {
        "group_id": "wr_archive_test",
        "content": "【致和法务】企业微信发送通道测试成功。",
    }


def test_wecomapi_group_members_returns_contact_names(client, db_session, monkeypatch):
    db_session.add(
        WeComArchiveGroup(
            room_id="wr_archive_members",
            wecomapi_room_id="room-platform-members",
            display_name="案件沟通群",
            status="enabled",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        WeComApiAdapter,
        "get_room_details",
        lambda self, room_ids: {
            "success": True,
            "rooms": [
                {
                    "roomId": room_ids[0],
                    "roomName": "案件沟通群",
                    "memberList": [
                        {"userId": "member-2", "name": "群昵称二"},
                        {"userId": "member-1", "name": ""},
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(
        WeComApiAdapter,
        "get_contact_details",
        lambda self, user_ids: {
            "success": True,
            "contacts": [
                {"userId": "member-1", "realName": "张律师", "nickname": "张三"},
                {"userId": "member-2", "realName": "", "nickname": "李经理"},
            ],
        },
    )

    response = client.get(
        "/api/v1/legal/wecomapi-settings/group-members",
        params={"room_id": "wr_archive_members"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "room_id": "wr_archive_members",
        "room_name": "案件沟通群",
        "members": [
            {"user_id": "member-1", "display_name": "张律师"},
            {"user_id": "member-2", "display_name": "李经理"},
        ],
        "warning": None,
    }


def test_wecomapi_group_members_rejects_unmapped_group(client, db_session):
    db_session.add(
        WeComArchiveGroup(
            room_id="wr_archive_unmapped",
            display_name="未映射群",
            status="enabled",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/legal/wecomapi-settings/group-members",
        params={"room_id": "wr_archive_unmapped"},
    )

    assert response.status_code == 400
    assert "尚未映射" in response.text


def test_wecomapi_group_members_falls_back_to_callback_cache(client, db_session, monkeypatch):
    db_session.add(
        WeComArchiveGroup(
            room_id="wr_archive_cached_members",
            wecomapi_room_id="room-platform-cached",
            display_name="回调成员群",
            status="enabled",
        )
    )
    db_session.add(
        WeComApiRoomMemberCache(
            guid="device-guid",
            room_id="room-platform-cached",
            user_id="member-cached-1",
            display_name="已发言成员",
            source="callback",
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        WeComApiAdapter,
        "get_room_details",
        lambda self, room_ids: {"success": False, "rooms": [], "error": "平台群详情暂不可用"},
    )
    monkeypatch.setattr(
        WeComApiAdapter,
        "get_contact_details",
        lambda self, user_ids: {"success": False, "contacts": [], "error": "联系人详情暂不可用"},
    )

    response = client.get(
        "/api/v1/legal/wecomapi-settings/group-members",
        params={"room_id": "wr_archive_cached_members"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["members"] == [{"user_id": "member-cached-1", "display_name": "已发言成员"}]
    assert "已在群里发过消息" in data["warning"]
