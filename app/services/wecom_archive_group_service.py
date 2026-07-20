from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.wecom_archive_group import WeComArchiveGroup
from app.schemas.legal import WeComArchiveGroupCreate, WeComArchiveGroupUpdate
from app.utils.datetime_utils import ensure_aware, now_tz


ARCHIVE_GROUP_STATUSES = {"discovered", "enabled", "disabled"}


class WeComArchiveGroupService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_group(self, room_id: str) -> WeComArchiveGroup | None:
        return self.db.scalar(select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == room_id))

    def list_groups(
        self,
        status: str | None = None,
        tenant_id: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[int, list[WeComArchiveGroup]]:
        query = select(WeComArchiveGroup)
        if status:
            self._validate_status(status)
            query = query.where(WeComArchiveGroup.status == status)
        if tenant_id:
            query = query.where(WeComArchiveGroup.tenant_id == tenant_id)
        items = list(
            self.db.scalars(
                query.order_by(WeComArchiveGroup.last_seen_at.desc(), WeComArchiveGroup.id.desc())
            ).all()
        )
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]

    def create_group(self, payload: WeComArchiveGroupCreate) -> WeComArchiveGroup:
        room_id = payload.room_id.strip()
        if self.get_group(room_id):
            raise ValueError("该群聊 roomid 已存在")
        self._validate_status(payload.status)
        self._validate_tenant(payload.tenant_id)
        group = WeComArchiveGroup(
            room_id=room_id,
            wecomapi_room_id=self._clean_optional(payload.wecomapi_room_id),
            display_name=self._clean_optional(payload.display_name),
            tenant_id=self._clean_optional(payload.tenant_id),
            status=payload.status,
        )
        self.db.add(group)
        self.db.flush()
        return group

    def update_group(self, room_id: str, payload: WeComArchiveGroupUpdate) -> WeComArchiveGroup:
        group = self.get_group(room_id)
        if not group:
            raise ValueError("归档群不存在")
        values = payload.model_dump(exclude_unset=True)
        if "status" in values:
            self._validate_status(values["status"])
        if "tenant_id" in values:
            self._validate_tenant(values["tenant_id"])
        for field in ("wecomapi_room_id", "display_name", "tenant_id"):
            if field in values:
                values[field] = self._clean_optional(values[field])
        for field, value in values.items():
            setattr(group, field, value)
        group.updated_at = now_tz()
        self.db.flush()
        return group

    def discover_group(self, room_id: str, seen_at: datetime) -> tuple[WeComArchiveGroup, bool]:
        group = self.get_group(room_id)
        observed_at = ensure_aware(seen_at)
        created = group is None
        if group is None:
            group = WeComArchiveGroup(
                room_id=room_id,
                status="discovered",
                seen_message_count=1,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
            self.db.add(group)
        else:
            group.seen_message_count += 1
            group.first_seen_at = group.first_seen_at or observed_at
            if group.last_seen_at is None or observed_at > group.last_seen_at:
                group.last_seen_at = observed_at
            group.updated_at = now_tz()
        self.db.flush()
        return group, created

    def identify_group(self, group: WeComArchiveGroup, display_name: str) -> bool:
        cleaned = " ".join(display_name.split())[:64]
        if not cleaned:
            return False
        group.display_name = cleaned
        group.updated_at = now_tz()
        self.db.flush()
        return True

    def _validate_tenant(self, tenant_id: str | None) -> None:
        cleaned = self._clean_optional(tenant_id)
        if cleaned and not self.db.scalar(select(Tenant.id).where(Tenant.tenant_id == cleaned)):
            raise ValueError("所属客户不存在")

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in ARCHIVE_GROUP_STATUSES:
            raise ValueError("群状态必须是 discovered、enabled 或 disabled")

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        cleaned = value.strip() if value else ""
        return cleaned or None
