from app.core.config import get_settings
from app.api.v1.wecomapi_callback import _callback_events
from app.models.wecomapi_room_cache import WeComApiRoomCache
from app.models.wecomapi_room_member_cache import WeComApiRoomMemberCache
from app.models.system_run_log import SystemRunLog
from sqlalchemy import select


def test_wecomapi_callback_ack_without_token(client, monkeypatch):
    monkeypatch.setenv("WECOMAPI_CALLBACK_TOKEN", "")
    get_settings.cache_clear()

    response = client.post(
        "/api/v1/wecomapi/callback",
        json={"guid": "device-guid", "cmd": "message", "msgType": "text", "requestId": "req-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0, "msg": "success", "data": {}}


def test_wecomapi_callback_requires_configured_path(client, monkeypatch):
    monkeypatch.setenv("WECOMAPI_CALLBACK_PATH_SECRET", "callback-secret")
    get_settings.cache_clear()

    response = client.post("/api/v1/wecomapi/callback", json={"guid": "device-guid"})

    assert response.status_code == 404
    assert response.json()["message"] == "回调地址无效"


def test_wecomapi_callback_accepts_secret_path(client, monkeypatch):
    monkeypatch.setenv("WECOMAPI_CALLBACK_PATH_SECRET", "callback-secret")
    get_settings.cache_clear()

    response = client.post("/api/v1/wecomapi/callback/callback-secret", json={"guid": "device-guid"})

    assert response.status_code == 200
    assert response.json()["code"] == 0


def test_wecomapi_callback_extracts_vendor_data_array():
    events = _callback_events(
        {
            "code": 0,
            "msg": "成功",
            "data": [
                {
                    "guid": "device-guid",
                    "cmd": 15000,
                    "msgType": 2,
                    "fromRoomId": 123456,
                    "msgData": {"content": "不应写入日志的消息正文"},
                }
            ],
        }
    )

    assert len(events) == 1
    assert events[0]["guid"] == "device-guid"
    assert events[0]["fromRoomId"] == 123456


def test_wecomapi_callback_rejects_non_event_envelope():
    assert _callback_events({"code": 0, "msg": "成功", "data": []}) == []


def test_wecomapi_callback_caches_group_room(client, db_session, monkeypatch):
    monkeypatch.setenv("WECOMAPI_CALLBACK_TOKEN", "")
    get_settings.cache_clear()

    response = client.post(
        "/api/v1/wecomapi/callback",
        json={
            "code": 0,
            "data": [
                {
                    "guid": "device-guid",
                    "cmd": 15000,
                    "msgType": 2,
                    "fromRoomId": 123456,
                    "senderId": 788130001,
                    "senderName": "张律师",
                    "msgData": {"content": "群缓存测试"},
                }
            ],
        },
    )

    assert response.status_code == 200
    cached = db_session.scalar(select(WeComApiRoomCache).where(WeComApiRoomCache.room_id == "123456"))
    assert cached is not None
    assert cached.guid == "device-guid"
    assert cached.room_name is None
    member = db_session.scalar(
        select(WeComApiRoomMemberCache).where(
            WeComApiRoomMemberCache.room_id == "123456",
            WeComApiRoomMemberCache.user_id == "788130001",
        )
    )
    assert member is not None
    assert member.display_name == "张律师"
    heartbeat = db_session.scalar(
        select(SystemRunLog)
        .where(SystemRunLog.run_type == "wecomapi_callback")
        .order_by(SystemRunLog.id.desc())
    )
    assert heartbeat is not None
    assert heartbeat.status == "success"
    assert heartbeat.total_count == 1
