from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.models.tenant import Tenant


def resource_scope_enabled(auth_context: dict[str, Any]) -> bool:
    settings = get_settings()
    return settings.auth_enabled and settings.rbac_enabled and settings.resource_scope_enabled


def tenant_scope_enabled(auth_context: dict[str, Any]) -> bool:
    settings = get_settings()
    return resource_scope_enabled(auth_context) and settings.tenant_enabled


def allowed_group_ids(auth_context: dict[str, Any]) -> list[str]:
    return list(auth_context.get("allowed_group_ids") or [])


def allowed_case_ids(auth_context: dict[str, Any]) -> list[int]:
    return [int(case_id) for case_id in (auth_context.get("allowed_case_ids") or [])]


def allowed_tenant_ids(auth_context: dict[str, Any]) -> list[str]:
    return list(auth_context.get("allowed_tenant_ids") or [])


def has_tenant_access(auth_context: dict[str, Any], tenant_id: str | None) -> bool:
    if not tenant_scope_enabled(auth_context):
        return True
    tenants = allowed_tenant_ids(auth_context)
    if auth_context.get("role") == "admin" and not tenants:
        return True
    if not tenants:
        return True
    if not tenant_id:
        return True
    return tenant_id in tenants


def has_tenant_data_access(db: Session, auth_context: dict[str, Any], tenant_id: str | None) -> bool:
    if not has_tenant_access(auth_context, tenant_id):
        return False
    if not tenant_id or auth_context.get("role") == "admin":
        return True
    tenant_status = db.scalar(select(Tenant.status).where(Tenant.tenant_id == tenant_id))
    return tenant_status != "disabled"


def has_group_access(auth_context: dict[str, Any], group_id: str | None, tenant_id: str | None = None) -> bool:
    if not resource_scope_enabled(auth_context) or auth_context.get("role") == "admin":
        return has_tenant_access(auth_context, tenant_id)
    if not has_tenant_access(auth_context, tenant_id):
        return False
    groups = allowed_group_ids(auth_context)
    if not groups:
        return True
    return bool(group_id and group_id in groups)


def has_case_access(db: Session, auth_context: dict[str, Any], case_id: int | None) -> bool:
    if case_id is None:
        return True
    legal_case = db.get(LegalCase, case_id)
    if not legal_case:
        return False
    if not has_tenant_data_access(db, auth_context, legal_case.tenant_id):
        return False
    if not resource_scope_enabled(auth_context) or auth_context.get("role") == "admin":
        return True
    cases = allowed_case_ids(auth_context)
    groups = allowed_group_ids(auth_context)
    if not cases and not groups:
        return True
    if int(case_id) in cases:
        return True
    return bool(legal_case and legal_case.group_id in groups)


def has_case_or_group_access(
    db: Session,
    auth_context: dict[str, Any],
    case_id: int | None,
    group_id: str | None,
    tenant_id: str | None = None,
) -> bool:
    if not has_tenant_data_access(db, auth_context, tenant_id):
        return False
    if case_id is not None:
        return has_case_access(db, auth_context, case_id)
    return has_group_access(auth_context, group_id, tenant_id)


def filter_cases(cases: list[LegalCase], auth_context: dict[str, Any], db: Session | None = None) -> list[LegalCase]:
    def tenant_ok(legal_case: LegalCase) -> bool:
        if db is None:
            return has_tenant_access(auth_context, legal_case.tenant_id)
        return has_tenant_data_access(db, auth_context, legal_case.tenant_id)

    if not resource_scope_enabled(auth_context) or auth_context.get("role") == "admin":
        return [case for case in cases if tenant_ok(case)]
    cases_scope = set(allowed_case_ids(auth_context))
    groups_scope = set(allowed_group_ids(auth_context))
    if not cases_scope and not groups_scope:
        return [case for case in cases if tenant_ok(case)]
    return [case for case in cases if tenant_ok(case) and (case.id in cases_scope or case.group_id in groups_scope)]


def filter_by_case_or_group(db: Session, items: list[Any], auth_context: dict[str, Any]) -> list[Any]:
    if not resource_scope_enabled(auth_context) or auth_context.get("role") == "admin":
        return [item for item in items if has_tenant_access(auth_context, getattr(item, "tenant_id", None))]
    return [
        item
        for item in items
        if has_case_or_group_access(
            db,
            auth_context,
            getattr(item, "case_id", None),
            getattr(item, "group_id", None),
            getattr(item, "tenant_id", None),
        )
    ]


def has_media_access(db: Session, auth_context: dict[str, Any], media_file: MediaFile) -> bool:
    return has_case_or_group_access(db, auth_context, media_file.case_id, media_file.group_id, media_file.tenant_id)


def has_reminder_access(db: Session, auth_context: dict[str, Any], reminder: Reminder) -> bool:
    return has_case_or_group_access(db, auth_context, reminder.case_id, reminder.group_id, reminder.tenant_id)


def has_sync_log_access(db: Session, auth_context: dict[str, Any], sync_log: DocumentSyncLog) -> bool:
    return has_tenant_data_access(db, auth_context, sync_log.tenant_id) and has_case_access(db, auth_context, sync_log.case_id)
