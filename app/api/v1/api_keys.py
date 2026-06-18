from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.db.session import get_db
from app.schemas.legal import ApiKeyCreate, ApiKeyCreateOut, ApiKeyListOut, ApiKeyOut, ApiKeyUpdate
from app.services.api_key_service import ApiKeyService

router = APIRouter(prefix="/legal/api-keys", tags=["legal-api-keys"])


@router.post("")
def create_api_key(
    payload: ApiKeyCreate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    try:
        result = ApiKeyService(db).create_api_key(
            name=payload.name,
            role=payload.role,
            expires_at=payload.expires_at,
            created_by=str(operator_info["operator"]),
            allowed_group_ids=payload.allowed_group_ids,
            allowed_case_ids=payload.allowed_case_ids,
            allowed_tenant_ids=payload.allowed_tenant_ids,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    except IntegrityError:
        db.rollback()
        raise_fail("API Key 创建失败，请重试", code=1500)
    record = result["record"]
    data = ApiKeyCreateOut(api_key=result["api_key"], **ApiKeyOut.model_validate(record).model_dump())
    return ok("创建成功，请立即保存 API Key，后续不会再次展示", data)


@router.get("")
def list_api_keys(
    role: str | None = None,
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    total, items = ApiKeyService(db).list_api_keys(role=role, is_active=is_active, page=page, page_size=page_size)
    return ok("查询成功", ApiKeyListOut(total=total, items=[ApiKeyOut.model_validate(item) for item in items]))


@router.patch("/{key_id}")
def update_api_key(key_id: int, payload: ApiKeyUpdate, db: Session = Depends(get_db)):
    try:
        api_key = ApiKeyService(db).update_api_key(
            key_id,
            role=payload.role,
            name=payload.name,
            expires_at=payload.expires_at,
            is_active=payload.is_active,
            allowed_group_ids=payload.allowed_group_ids,
            allowed_case_ids=payload.allowed_case_ids,
            allowed_tenant_ids=payload.allowed_tenant_ids,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1404)
    return ok("更新成功", ApiKeyOut.model_validate(api_key))


@router.post("/{key_id}/revoke")
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    try:
        api_key = ApiKeyService(db).revoke_api_key(key_id, operator=str(operator_info["operator"]))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1404)
    return ok("吊销成功", ApiKeyOut.model_validate(api_key))
