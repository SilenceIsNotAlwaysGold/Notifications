from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok
from app.api.v1.response import raise_fail
from app.core.resource_permissions import has_group_access, has_tenant_data_access
from app.db.session import get_db
from app.models.legal_case import LegalCase
from app.schemas.legal import MessageProcessOut, MockMessageCreate
from app.services.message_service import MessageService

router = APIRouter(prefix="/legal/messages", tags=["legal-messages"])


@router.post("/mock")
def receive_mock_message(
    payload: MockMessageCreate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    inferred_tenant_id = payload.tenant_id or db.scalar(
        select(LegalCase.tenant_id)
        .where(LegalCase.group_id == payload.group_id)
        .where(LegalCase.tenant_id.is_not(None))
        .order_by(LegalCase.id.asc())
    )
    if not has_tenant_data_access(db, operator_info, inferred_tenant_id) or not has_group_access(operator_info, payload.group_id, inferred_tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    result = MessageService(db).handle_mock_message(payload)
    db.commit()
    return ok("群消息处理成功", MessageProcessOut(**result))
