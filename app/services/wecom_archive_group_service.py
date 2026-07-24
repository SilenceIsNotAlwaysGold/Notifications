from datetime import datetime
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.wecom_archive_group import WeComArchiveGroup
from app.schemas.legal import WeComArchiveGroupCreate, WeComArchiveGroupUpdate
from app.utils.datetime_utils import ensure_aware, now_tz


ARCHIVE_GROUP_STATUSES = {"discovered", "enabled", "disabled"}
ARCHIVE_GROUP_TYPES = {"merchant", "debtor", "internal", "other"}
ARCHIVE_ACCESS_POLICIES = {"auto", "whitelist", "blacklist"}
GROUP_FEATURE_DEFAULTS = {
    "ocr": True,
    "document_sync": True,
    "payment_tracking": True,
    "case_reminders": True,
    "question_timeout": True,
}


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
        self._validate_group_type(payload.group_type)
        self._validate_access_policy(payload.access_policy)
        self._validate_tenant(payload.tenant_id)
        group = WeComArchiveGroup(
            room_id=room_id,
            wecomapi_room_id=self._clean_optional(payload.wecomapi_room_id),
            display_name=self._clean_optional(payload.display_name),
            tenant_id=self._clean_optional(payload.tenant_id),
            status=payload.status,
            group_type=payload.group_type,
            access_policy=payload.access_policy,
            features_json=json.dumps(self._normalize_features(payload.features), ensure_ascii=False),
            internal_userids_json=json.dumps(self._normalize_userids(payload.internal_userids), ensure_ascii=False),
            alert_userids_json=json.dumps(self._normalize_userids(payload.alert_userids), ensure_ascii=False),
            question_timeout_minutes=payload.question_timeout_minutes,
        )
        self._apply_name_classification(group)
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
        if "group_type" in values:
            self._validate_group_type(values["group_type"])
        if "access_policy" in values:
            self._validate_access_policy(values["access_policy"])
        if "tenant_id" in values:
            self._validate_tenant(values["tenant_id"])
        for field in ("wecomapi_room_id", "display_name", "tenant_id"):
            if field in values:
                values[field] = self._clean_optional(values[field])
        if "features" in values:
            values["features_json"] = json.dumps(self._normalize_features(values.pop("features")), ensure_ascii=False)
        if "internal_userids" in values:
            values["internal_userids_json"] = json.dumps(self._normalize_userids(values.pop("internal_userids")), ensure_ascii=False)
        if "alert_userids" in values:
            values["alert_userids_json"] = json.dumps(self._normalize_userids(values.pop("alert_userids")), ensure_ascii=False)
        for field, value in values.items():
            setattr(group, field, value)
        self._apply_name_classification(group)
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
                group_type="other",
                access_policy="auto",
                features_json=json.dumps(GROUP_FEATURE_DEFAULTS, ensure_ascii=False),
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
        self._apply_name_classification(group)
        group.updated_at = now_tz()
        self.db.flush()
        return True

    def classify_group_name(self, group: WeComArchiveGroup) -> bool:
        before = (group.status, group.group_type)
        self._apply_name_classification(group)
        changed = before != (group.status, group.group_type)
        if changed:
            group.updated_at = now_tz()
            self.db.flush()
        return changed

    @staticmethod
    def _apply_name_classification(group: WeComArchiveGroup) -> None:
        if group.access_policy == "blacklist":
            group.status = "disabled"
            return
        if group.access_policy == "whitelist":
            group.status = "enabled"
            return
        name = group.display_name or ""
        if "法务起诉沟通群" in name:
            group.status = "enabled"
            group.group_type = "merchant"
        elif "还款对接群" in name:
            group.status = "enabled"
            group.group_type = "debtor"

    def feature_enabled(self, room_id: str, feature: str) -> bool:
        if feature not in GROUP_FEATURE_DEFAULTS:
            raise ValueError(f"未知群功能：{feature}")
        group = self.get_group(room_id)
        if group is None:
            return GROUP_FEATURE_DEFAULTS[feature]
        features = self.features(group)
        return bool(features.get(feature, GROUP_FEATURE_DEFAULTS[feature]))

    @staticmethod
    def features(group: WeComArchiveGroup) -> dict[str, bool]:
        try:
            configured = json.loads(group.features_json or "{}")
        except (TypeError, ValueError):
            configured = {}
        return {**GROUP_FEATURE_DEFAULTS, **{key: bool(value) for key, value in configured.items() if key in GROUP_FEATURE_DEFAULTS}}

    @staticmethod
    def internal_userids(group: WeComArchiveGroup) -> list[str]:
        return WeComArchiveGroupService._load_userids(group.internal_userids_json)

    @staticmethod
    def alert_userids(group: WeComArchiveGroup) -> list[str]:
        return WeComArchiveGroupService._load_userids(group.alert_userids_json)

    def _validate_tenant(self, tenant_id: str | None) -> None:
        cleaned = self._clean_optional(tenant_id)
        if cleaned and not self.db.scalar(select(Tenant.id).where(Tenant.tenant_id == cleaned)):
            raise ValueError("所属客户不存在")

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in ARCHIVE_GROUP_STATUSES:
            raise ValueError("群状态必须是 discovered、enabled 或 disabled")

    @staticmethod
    def _validate_group_type(group_type: str) -> None:
        if group_type not in ARCHIVE_GROUP_TYPES:
            raise ValueError("群类型必须是 merchant、debtor、internal 或 other")

    @staticmethod
    def _validate_access_policy(access_policy: str) -> None:
        if access_policy not in ARCHIVE_ACCESS_POLICIES:
            raise ValueError("群接入策略必须是 auto、whitelist 或 blacklist")

    @staticmethod
    def _normalize_features(features: dict[str, bool] | None) -> dict[str, bool]:
        configured = features or {}
        unknown = set(configured) - set(GROUP_FEATURE_DEFAULTS)
        if unknown:
            raise ValueError(f"未知群功能：{', '.join(sorted(unknown))}")
        if any(not isinstance(value, bool) for value in configured.values()):
            raise ValueError("群功能开关必须是布尔值")
        return {**GROUP_FEATURE_DEFAULTS, **configured}

    @staticmethod
    def _normalize_userids(userids: list[str] | None) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in (userids or []) if value and value.strip()))

    @staticmethod
    def _load_userids(raw: str | None) -> list[str]:
        try:
            values = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return [str(value) for value in values if value]

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        cleaned = value.strip() if value else ""
        return cleaned or None
