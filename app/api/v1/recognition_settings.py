from fastapi import APIRouter, Depends

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.config import get_settings
from app.schemas.recognition_settings import RecognitionSettingsUpdate
from app.services.recognition_settings_service import RecognitionSettingsService


router = APIRouter(prefix="/legal/recognition-settings", tags=["legal-recognition-settings"])


def _admin_operator(
    operator_info: dict[str, object] = Depends(get_current_operator),
) -> dict[str, object]:
    if operator_info.get("role") != "admin":
        raise_fail("仅管理员可以管理识别与 AI 配置", code=403, status_code=403)
    return operator_info


@router.get("", dependencies=[Depends(_admin_operator)])
def get_recognition_settings():
    return ok("查询成功", RecognitionSettingsService(get_settings()).current())


@router.put("", dependencies=[Depends(_admin_operator)])
def update_recognition_settings(payload: RecognitionSettingsUpdate):
    service = RecognitionSettingsService(get_settings())
    service.update(payload)
    return ok("识别与 AI 配置已保存", service.current())


@router.post("/check", dependencies=[Depends(_admin_operator)])
def check_recognition_services():
    return ok("检测完成", RecognitionSettingsService(get_settings()).check())
