from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.config import get_settings
from app.db.session import get_db
from app.adapters.wecom_message import WeComMessageAdapter
from app.schemas.wecomapi_settings import (
    WeComApiGroupMembersOut,
    WeComApiGroupSyncOut,
    WeComApiSettingsUpdate,
    WeComApiTestSendRequest,
)
from app.services.wecomapi_group_sync_service import WeComApiGroupSyncService
from app.services.wecomapi_settings_service import WeComApiSettingsService

router = APIRouter(prefix="/legal/wecomapi-settings", tags=["legal-wecomapi-settings"])


def _admin_operator(
    operator_info: dict[str, object] = Depends(get_current_operator),
) -> dict[str, object]:
    if operator_info.get("role") != "admin":
        raise_fail("仅管理员可以管理第三方发送平台", code=403, status_code=403)
    return operator_info


@router.get("", dependencies=[Depends(_admin_operator)])
def get_wecomapi_settings(request: Request):
    service = WeComApiSettingsService(get_settings())
    return ok("查询成功", service.current(_callback_url(request)))


@router.put("", dependencies=[Depends(_admin_operator)])
def update_wecomapi_settings(payload: WeComApiSettingsUpdate, request: Request):
    service = WeComApiSettingsService(get_settings())
    service.update(payload)
    return ok("第三方发送平台配置已保存", service.current(_callback_url(request)))


@router.post("/check-login", dependencies=[Depends(_admin_operator)])
def check_wecomapi_login():
    return ok("查询成功", WeComApiSettingsService(get_settings()).check_login())


@router.post("/sync-groups", dependencies=[Depends(_admin_operator)])
def sync_wecomapi_groups(db: Session = Depends(get_db)):
    try:
        result = WeComApiGroupSyncService(db).sync()
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("平台群资料同步完成", WeComApiGroupSyncOut(**result))


@router.get("/group-members", dependencies=[Depends(_admin_operator)])
def get_wecomapi_group_members(room_id: str, db: Session = Depends(get_db)):
    try:
        result = WeComApiGroupSyncService(db).members(room_id.strip())
    except ValueError as exc:
        raise_fail(str(exc), code=1400)
    return ok("群成员查询成功", WeComApiGroupMembersOut(**result))


@router.post("/test-send", dependencies=[Depends(_admin_operator)])
def test_wecomapi_send(payload: WeComApiTestSendRequest):
    result = WeComMessageAdapter().send_text(payload.room_id, payload.content)
    if not result.get("success"):
        raise_fail(result.get("error") or "测试消息发送失败", code=1400)
    return ok(
        "测试消息发送成功",
        {"success": True, "mode": result.get("mode"), "status_code": result.get("status_code")},
    )


def _callback_url(request: Request) -> str:
    headers = request.headers
    proto = headers.get("x-forwarded-proto") or request.url.scheme
    host = headers.get("x-forwarded-host") or headers.get("host") or request.url.netloc
    secret = get_settings().wecomapi_callback_path_secret
    suffix = f"/{secret}" if secret else ""
    return f"{proto}://{host}/api/v1/wecomapi/callback{suffix}"
