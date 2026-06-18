import hashlib
import json
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import ROLES, permission_names
from app.models.api_key import ApiKey
from app.utils.datetime_utils import ensure_aware, now_tz


class ApiKeyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @staticmethod
    def key_prefix(raw_key: str) -> str:
        return raw_key[:6]

    @staticmethod
    def generate_key() -> str:
        return f"lwk_live_{secrets.token_urlsafe(24)}"

    def create_api_key(
        self,
        name: str | None,
        role: str,
        expires_at: datetime | None,
        created_by: str | None,
        allowed_group_ids: list[str] | None = None,
        allowed_case_ids: list[int] | None = None,
        allowed_tenant_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        self._validate_role(role)
        raw_key = self.generate_key()
        api_key = ApiKey(
            key_hash=self.hash_key(raw_key),
            key_prefix=self.key_prefix(raw_key),
            name=name,
            role=role,
            expires_at=ensure_aware(expires_at) if expires_at else None,
            allowed_group_ids_json=self._dump_scope(allowed_group_ids),
            allowed_case_ids_json=self._dump_scope(allowed_case_ids),
            allowed_tenant_ids_json=self._dump_scope(allowed_tenant_ids),
            created_by=created_by,
        )
        self.db.add(api_key)
        self.db.flush()
        return {"api_key": raw_key, "record": api_key}

    def verify_api_key(self, raw_key: str, client_host: str | None = None) -> dict[str, Any] | None:
        key_hash = self.hash_key(raw_key)
        api_key = self.db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
        if api_key:
            if not api_key.is_active:
                return None
            if api_key.expires_at and ensure_aware(api_key.expires_at) <= now_tz():
                return None
            api_key.last_used_at = now_tz()
            api_key.last_used_ip = client_host
            self.db.flush()
            return {
                "source": "database",
                "role": api_key.role,
                "key_id": api_key.id,
                "key_prefix": api_key.key_prefix,
                "name": api_key.name,
                "permissions": permission_names(api_key.role),
                "allowed_group_ids": self._load_scope(api_key.allowed_group_ids_json),
                "allowed_case_ids": self._load_scope(api_key.allowed_case_ids_json),
                "allowed_tenant_ids": self._load_scope(api_key.allowed_tenant_ids_json),
            }

        if raw_key in self.settings.admin_api_key_list:
            role = self.settings.default_api_key_role
            return {
                "source": "env",
                "role": role,
                "key_id": None,
                "key_prefix": self.key_prefix(raw_key),
                "name": "env-admin-api-key",
                "permissions": permission_names(role),
                "allowed_group_ids": [],
                "allowed_case_ids": [],
                "allowed_tenant_ids": [],
            }
        return None

    def list_api_keys(
        self,
        role: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[ApiKey]]:
        query = select(ApiKey)
        if role:
            query = query.where(ApiKey.role == role)
        if is_active is not None:
            query = query.where(ApiKey.is_active == is_active)
        items = list(self.db.scalars(query.order_by(ApiKey.id.desc())).all())
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]

    def update_api_key(
        self,
        key_id: int,
        role: str | None = None,
        name: str | None = None,
        expires_at: datetime | None = None,
        is_active: bool | None = None,
        allowed_group_ids: list[str] | None = None,
        allowed_case_ids: list[int] | None = None,
        allowed_tenant_ids: list[str] | None = None,
    ) -> ApiKey:
        api_key = self._get_api_key(key_id)
        if role is not None:
            self._validate_role(role)
            api_key.role = role
        if name is not None:
            api_key.name = name
        if expires_at is not None:
            api_key.expires_at = ensure_aware(expires_at)
        if is_active is not None:
            api_key.is_active = is_active
        if allowed_group_ids is not None:
            api_key.allowed_group_ids_json = self._dump_scope(allowed_group_ids)
        if allowed_case_ids is not None:
            api_key.allowed_case_ids_json = self._dump_scope(allowed_case_ids)
        if allowed_tenant_ids is not None:
            api_key.allowed_tenant_ids_json = self._dump_scope(allowed_tenant_ids)
        api_key.updated_at = now_tz()
        self.db.flush()
        return api_key

    def revoke_api_key(self, key_id: int, operator: str | None) -> ApiKey:
        api_key = self._get_api_key(key_id)
        api_key.is_active = False
        api_key.revoked_at = now_tz()
        api_key.revoked_by = operator
        api_key.updated_at = now_tz()
        self.db.flush()
        return api_key

    def _get_api_key(self, key_id: int) -> ApiKey:
        api_key = self.db.get(ApiKey, key_id)
        if not api_key:
            raise ValueError("API Key 不存在")
        return api_key

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in ROLES:
            raise ValueError("无效角色")

    @staticmethod
    def _dump_scope(values: list[str] | list[int] | None) -> str:
        return json.dumps(values or [], ensure_ascii=False)

    @staticmethod
    def _load_scope(raw: str | None) -> list[Any]:
        if not raw:
            return []
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except Exception:
            return []
