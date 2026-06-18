from fastapi import HTTPException, Request

from app.core.config import get_settings
from app.core.permissions import has_permission
from app.db.session import SessionLocal
from app.services.api_key_service import ApiKeyService


def _is_public_endpoint(path: str) -> bool:
    settings = get_settings()
    normalized_path = path.rstrip("/") or "/"
    return any(normalized_path == endpoint.rstrip("/") for endpoint in settings.public_endpoint_list)


def _store_operator_state(request: Request, operator_info: dict[str, object]) -> None:
    request.state.operator = operator_info.get("operator")
    request.state.auth_type = operator_info.get("auth_type")
    request.state.operator_role = operator_info.get("role")
    request.state.api_key_id = operator_info.get("key_id")
    request.state.api_key_prefix = operator_info.get("key_prefix")
    request.state.resource_scope = {
        "allowed_group_ids": operator_info.get("allowed_group_ids") or [],
        "allowed_case_ids": operator_info.get("allowed_case_ids") or [],
        "allowed_tenant_ids": operator_info.get("allowed_tenant_ids") or [],
    }


def get_current_operator(request: Request) -> dict[str, object]:
    settings = get_settings()
    if not settings.auth_enabled:
        operator_info = {
            "operator": "anonymous-dev",
            "auth_type": "disabled",
            "role": "admin",
            "key_id": None,
            "key_prefix": None,
            "permissions": ["all"],
            "allowed_group_ids": [],
            "allowed_case_ids": [],
            "allowed_tenant_ids": [],
        }
        _store_operator_state(request, operator_info)
        return operator_info

    if _is_public_endpoint(request.url.path):
        operator_info = {
            "operator": "anonymous-public",
            "auth_type": "public",
            "role": "public",
            "key_id": None,
            "key_prefix": None,
            "permissions": [],
            "allowed_group_ids": [],
            "allowed_case_ids": [],
            "allowed_tenant_ids": [],
        }
        _store_operator_state(request, operator_info)
        return operator_info

    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail={"code": 401, "message": "未提供 API Key", "data": None})

    db = SessionLocal()
    try:
        client_host = request.client.host if request.client else None
        verified = ApiKeyService(db).verify_api_key(api_key, client_host=client_host)
        if not verified:
            raise HTTPException(status_code=401, detail={"code": 401, "message": "API Key 无效或已过期", "data": None})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=401, detail={"code": 401, "message": "API Key 校验失败", "data": None})
    finally:
        db.close()

    role = str(verified["role"])
    if settings.rbac_enabled and not has_permission(role, request.method, request.url.path):
        operator_info = {
            "operator": request.headers.get("X-Operator") or verified.get("name") or "api-key-admin",
            "auth_type": "api_key",
            "role": role,
            "key_id": verified.get("key_id"),
            "key_prefix": verified.get("key_prefix"),
            "permissions": verified.get("permissions") or [],
            "allowed_group_ids": verified.get("allowed_group_ids") or [],
            "allowed_case_ids": verified.get("allowed_case_ids") or [],
            "allowed_tenant_ids": verified.get("allowed_tenant_ids") or [],
        }
        _store_operator_state(request, operator_info)
        raise HTTPException(status_code=403, detail={"code": 403, "message": "无权限访问该接口", "data": None})

    operator_info = {
        "operator": request.headers.get("X-Operator") or verified.get("name") or "api-key-admin",
        "auth_type": "api_key",
        "role": role,
        "key_id": verified.get("key_id"),
        "key_prefix": verified.get("key_prefix"),
        "permissions": verified.get("permissions") or [],
        "allowed_group_ids": verified.get("allowed_group_ids") or [],
        "allowed_case_ids": verified.get("allowed_case_ids") or [],
        "allowed_tenant_ids": verified.get("allowed_tenant_ids") or [],
    }
    _store_operator_state(request, operator_info)
    return operator_info
