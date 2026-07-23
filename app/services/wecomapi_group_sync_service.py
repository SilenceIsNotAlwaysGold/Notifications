from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.wecomapi import WeComApiAdapter
from app.core.config import Settings, get_settings
from app.models.wecom_archive_group import WeComArchiveGroup
from app.models.wecomapi_room_cache import WeComApiRoomCache
from app.models.wecomapi_room_member_cache import WeComApiRoomMemberCache
from app.utils.datetime_utils import now_tz


class WeComApiGroupSyncService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        adapter: WeComApiAdapter | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.adapter = adapter or WeComApiAdapter(
            base_url=self.settings.wecomapi_base_url,
            api_path=self.settings.wecomapi_api_path,
            token=self.settings.wecomapi_token,
            token_header=self.settings.wecomapi_token_header,
            guid=self.settings.wecomapi_guid,
            timeout_seconds=self.settings.wecom_timeout_seconds,
            min_interval_seconds=self.settings.wecomapi_min_interval_seconds,
            daily_limit=self.settings.wecomapi_daily_limit,
            failure_threshold=self.settings.wecomapi_failure_threshold,
            cooldown_seconds=self.settings.wecomapi_cooldown_seconds,
        )

    def sync(self) -> dict[str, Any]:
        result = self.adapter.list_rooms()
        if not result.get("success"):
            raise ValueError(result.get("error") or "平台群资料同步失败")
        normalized_rooms = [self._normalize_room(item) for item in result.get("rooms") or []]
        room_by_id = {item["room_id"]: item for item in normalized_rooms if item is not None}
        cached_rooms = list(
            self.db.scalars(
                select(WeComApiRoomCache).where(WeComApiRoomCache.guid == (self.settings.wecomapi_guid or ""))
            ).all()
        )
        if cached_rooms:
            detail_result = self.adapter.get_room_details([item.room_id for item in cached_rooms])
            if detail_result.get("success"):
                for raw_room in detail_result.get("rooms") or []:
                    room = self._normalize_room(raw_room)
                    if room:
                        room_by_id[room["room_id"]] = self._merge_room(room, room_by_id.get(room["room_id"]))
        for cached in cached_rooms:
            fallback = {
                "room_id": cached.room_id,
                "room_name": cached.room_name,
                "owner_userid": cached.owner_userid,
                "member_count": cached.member_count,
                "avatar_url": None,
                "created_at": None,
                "updated_at": cached.updated_at.isoformat() if cached.updated_at else None,
            }
            room_by_id[cached.room_id] = self._merge_room(room_by_id.get(cached.room_id), fallback)
        rooms = list(room_by_id.values())
        self._update_cache(rooms)
        mapped_groups = list(
            self.db.scalars(
                select(WeComArchiveGroup).where(WeComArchiveGroup.wecomapi_room_id.in_(room_by_id))
            ).all()
        ) if room_by_id else []
        updated = 0
        for group in mapped_groups:
            room = room_by_id[group.wecomapi_room_id]
            if room["room_name"] and group.display_name != room["room_name"]:
                group.display_name = room["room_name"]
                group.updated_at = now_tz()
                updated += 1
        self.db.flush()
        return {
            "fetched": len(rooms),
            "mapped": len(mapped_groups),
            "updated": updated,
            "rooms": rooms,
        }

    def members(self, archive_room_id: str) -> dict[str, Any]:
        group = self.db.scalar(
            select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == archive_room_id)
        )
        if not group or group.status != "enabled":
            raise ValueError("确认群不存在或未启用")
        if not group.wecomapi_room_id:
            raise ValueError("确认群尚未映射到 wecomapi 群")

        cached_members = list(
            self.db.scalars(
                select(WeComApiRoomMemberCache).where(
                    WeComApiRoomMemberCache.room_id == group.wecomapi_room_id
                )
            ).all()
        )
        members_by_id: dict[str, dict[str, str]] = {
            member.user_id: {
                "user_id": member.user_id,
                "display_name": member.display_name or member.user_id,
            }
            for member in cached_members
        }

        detail_result = self.adapter.get_room_details([group.wecomapi_room_id])
        room = next(
            (
                item
                for item in detail_result.get("rooms") or []
                if str(item.get("roomId") or "").strip() == group.wecomapi_room_id
            ),
            None,
        )
        if detail_result.get("success") and not room:
            raise ValueError("平台未返回目标群详情")

        raw_members = room.get("memberList") if room and isinstance(room.get("memberList"), list) else []
        for member in raw_members:
            if not isinstance(member, dict):
                continue
            user_id = str(member.get("userId") or "").strip()
            if not user_id:
                continue
            room_name = str(member.get("name") or member.get("roomRemarkName") or "").strip()
            members_by_id[user_id] = {"user_id": user_id, "display_name": room_name or user_id}

        if members_by_id:
            contact_result = self.adapter.get_contact_details(list(members_by_id))
            if contact_result.get("success"):
                for contact in contact_result.get("contacts") or []:
                    user_id = str(contact.get("userId") or "").strip()
                    if user_id not in members_by_id:
                        continue
                    display_name = str(
                        contact.get("realName") or contact.get("nickname") or contact.get("alias") or ""
                    ).strip()
                    if display_name:
                        members_by_id[user_id]["display_name"] = display_name

        return {
            "room_id": archive_room_id,
            "room_name": str((room or {}).get("roomName") or group.display_name or "").strip() or None,
            "members": sorted(
                members_by_id.values(),
                key=lambda item: (item["display_name"].casefold(), item["user_id"]),
            ),
            "warning": (
                None
                if detail_result.get("success")
                else "平台暂时无法读取全量群成员，当前展示已在群里发过消息的人员"
            ),
        }

    def _update_cache(self, rooms: list[dict[str, Any]]) -> None:
        cached_by_id = {
            item.room_id: item
            for item in self.db.scalars(
                select(WeComApiRoomCache).where(
                    WeComApiRoomCache.room_id.in_([room["room_id"] for room in rooms])
                )
            ).all()
        } if rooms else {}
        now = now_tz()
        for room in rooms:
            cached = cached_by_id.get(room["room_id"])
            if cached is None:
                cached = WeComApiRoomCache(
                    guid=(self.settings.wecomapi_guid or "")[:128],
                    room_id=room["room_id"],
                    source="list",
                    first_seen_at=now,
                    last_seen_at=now,
                )
                self.db.add(cached)
            if room.get("room_name"):
                cached.room_name = room["room_name"]
            if room.get("owner_userid"):
                cached.owner_userid = room["owner_userid"]
            if room.get("member_count") is not None:
                cached.member_count = room["member_count"]
            cached.updated_at = now

    @staticmethod
    def _merge_room(primary: dict[str, Any] | None, fallback: dict[str, Any] | None) -> dict[str, Any]:
        primary = primary or {}
        fallback = fallback or {}
        return {
            key: primary.get(key) if primary.get(key) is not None else fallback.get(key)
            for key in ("room_id", "room_name", "owner_userid", "member_count", "avatar_url", "created_at", "updated_at")
        }

    @staticmethod
    def _normalize_room(room: Any) -> dict[str, Any] | None:
        if not isinstance(room, dict):
            return None
        room_id = str(room.get("roomId") or "").strip()
        if not room_id:
            return None
        member_count = room.get("roomMemberCount")
        if member_count is None and isinstance(room.get("memberList"), list):
            member_count = len(room["memberList"])
        try:
            member_count = int(member_count) if member_count is not None else None
        except (TypeError, ValueError):
            member_count = None
        return {
            "room_id": room_id[:128],
            "room_name": str(room.get("roomName") or "").strip()[:255] or None,
            "owner_userid": str(room.get("roomOwnerId") or room.get("roomCreateUserId") or "").strip()[:128] or None,
            "member_count": member_count,
            "avatar_url": str(room.get("roomAvatarUrl") or "").strip()[:2000] or None,
            "created_at": str(room.get("roomCreateTime") or "").strip()[:64] or None,
            "updated_at": str(room.get("roomUpdateTime") or "").strip()[:64] or None,
        }
