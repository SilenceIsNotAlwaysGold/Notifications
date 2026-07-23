from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.wecomapi_room_cache import WeComApiRoomCache
from app.models.wecomapi_room_member_cache import WeComApiRoomMemberCache
from app.utils.datetime_utils import now_tz


class WeComApiRoomCacheService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record_event(self, event: dict[str, Any]) -> WeComApiRoomCache | None:
        room_id = self._text(event.get("fromRoomId") or event.get("from_room_id"), 128)
        guid = self._text(event.get("guid"), 128)
        if not room_id or not guid:
            return None
        msg_data = event.get("msgData") if isinstance(event.get("msgData"), dict) else {}
        room_name = self._text(
            event.get("roomName")
            or event.get("fromRoomName")
            or msg_data.get("roomName")
            or msg_data.get("fromRoomName"),
            255,
        )
        cached = self.db.scalar(select(WeComApiRoomCache).where(WeComApiRoomCache.room_id == room_id))
        now = now_tz()
        if cached is None:
            cached = WeComApiRoomCache(
                guid=guid,
                room_id=room_id,
                room_name=room_name,
                source="callback",
                first_seen_at=now,
                last_seen_at=now,
            )
            self.db.add(cached)
        else:
            cached.guid = guid
            cached.last_seen_at = now
            if room_name:
                cached.room_name = room_name
        self._record_member(event, guid, room_id, now)
        return cached

    def _record_member(self, event: dict[str, Any], guid: str, room_id: str, now) -> None:
        msg_data = event.get("msgData") if isinstance(event.get("msgData"), dict) else {}
        user_id = self._text(event.get("senderId") or msg_data.get("senderId"), 128)
        if not user_id:
            return
        display_name = self._text(
            event.get("senderName") or msg_data.get("senderName") or msg_data.get("nickname"),
            255,
        )
        member = self.db.scalar(
            select(WeComApiRoomMemberCache).where(
                WeComApiRoomMemberCache.room_id == room_id,
                WeComApiRoomMemberCache.user_id == user_id,
            )
        )
        if member is None:
            member = WeComApiRoomMemberCache(
                guid=guid,
                room_id=room_id,
                user_id=user_id,
                display_name=display_name,
                source="callback",
                first_seen_at=now,
                last_seen_at=now,
            )
            self.db.add(member)
            return
        member.guid = guid
        member.last_seen_at = now
        member.updated_at = now
        if display_name:
            member.display_name = display_name

    @staticmethod
    def _text(value: Any, max_length: int) -> str | None:
        text = str(value or "").strip()
        return text[:max_length] or None
