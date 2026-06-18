from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok
from app.api.v1.response import raise_fail
from app.core.resource_permissions import filter_by_case_or_group, has_case_access
from app.db.session import get_db
from app.models.legal_event import LegalEvent
from app.schemas.legal import EventListOut, EventOut

router = APIRouter(prefix="/legal/events", tags=["legal-events"])


@router.get("")
def list_events(
    event_type: str | None = None,
    case_id: int | None = None,
    tenant_id: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if case_id is not None and not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    query = select(LegalEvent)
    if event_type:
        query = query.where(LegalEvent.event_type == event_type)
    if case_id is not None:
        query = query.where(LegalEvent.case_id == case_id)
    if tenant_id is not None:
        query = query.where(LegalEvent.tenant_id == tenant_id)
    items = list(db.scalars(query.order_by(LegalEvent.id.desc())).all())
    items = filter_by_case_or_group(db, items, operator_info)
    data = EventListOut(total=len(items), items=[EventOut.model_validate(item) for item in items[offset : offset + limit]])
    return ok("事件查询成功", data)
