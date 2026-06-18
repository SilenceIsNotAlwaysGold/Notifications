from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.adapters.wecom_archive import WeComArchiveAdapter
from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok
from app.db.session import get_db
from app.schemas.legal import WeComArchivePullOut, WeComArchiveReplayRequest

router = APIRouter(prefix="/legal/wecom-archive", tags=["legal-wecom-archive"])


@router.post("/pull")
def pull_wecom_archive(db: Session = Depends(get_db), operator_info: dict[str, str] = Depends(get_current_operator)):
    result = WeComArchiveAdapter().pull_and_process(db, trigger_type="api", operator=operator_info["operator"])
    db.commit()
    return ok("拉取完成", WeComArchivePullOut(**result))


@router.post("/replay")
def replay_wecom_archive(payload: WeComArchiveReplayRequest, db: Session = Depends(get_db)):
    result = WeComArchiveAdapter(mock_messages=payload.messages).replay_messages(db, payload.messages)
    db.commit()
    return ok("回放完成", WeComArchivePullOut(**result))
